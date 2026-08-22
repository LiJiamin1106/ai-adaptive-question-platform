"""RAG 检索：Qdrant 混合检索（dense + BM25）+ cross-encoder 重排。

语料：data/syllabus.json（考纲）+ data/examples.json（真题 few-shot）。
流程：
  1. 每个 chunk 用 fastembed 算 dense + sparse 向量，入 Qdrant（本地落盘）
  2. 查询：dense / sparse 分别检索 → RRF 融合 → cross-encoder 重排
  3. 返回相关真题 few-shot + 考纲上下文

模型（首次自动下载，需走 HF 镜像，见 .env）：
  dense  BAAI/bge-small-en-v1.5
  sparse Qdrant/bm25
  rerank cross-encoder/ms-marco-MiniLM-L-6-v2
"""
import json
import os
import uuid

from dotenv import load_dotenv

load_dotenv()

from fastembed import SparseTextEmbedding, TextEmbedding
from qdrant_client import QdrantClient, models
from sentence_transformers import CrossEncoder

from schemas import GenerateRequest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
QDRANT_PATH = os.path.join(BASE_DIR, "qdrant_data")
COLLECTION = "apcsa"

DENSE_DIM = 384
DENSE_MODEL = "BAAI/bge-small-en-v1.5"
SPARSE_MODEL = "Qdrant/bm25"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

_dense = None
_sparse = None
_rerank = None
_client = None


def _qid(stem: str) -> str:
    """题干的稳定 UUID（幂等 upsert + 精确删除）。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, stem))


def _models():
    global _dense, _sparse, _rerank
    if _dense is None:
        _dense = TextEmbedding(DENSE_MODEL)
        _sparse = SparseTextEmbedding(SPARSE_MODEL)
        _rerank = CrossEncoder(RERANK_MODEL)
    return _dense, _sparse, _rerank


def _get_client():
    global _client
    if _client is None:
        _client = QdrantClient(path=QDRANT_PATH)
    return _client


def _docs():
    """把考纲 + 真题拼成 (text, payload) 文档列表。"""
    with open(os.path.join(DATA_DIR, "syllabus.json"), encoding="utf-8") as f:
        syllabus = json.load(f)
    # 真题样例：手选 examples.json + PDF 解析出的 questions.json 一起进索引
    examples = []
    for name in ("examples.json", "questions.json"):
        path = os.path.join(DATA_DIR, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                examples.extend(json.load(f))
    docs = []
    for u in syllabus:
        for t in u["topics"]:
            text = f"Unit {u['unit']}: {u['unit_name']} - {t}"
            docs.append({"qid": _qid(text), "text": text, "payload": {
                "kind": "syllabus", "text": text,
                "unit": u["unit"], "unit_name": u["unit_name"], "topic": t,
            }})
    for e in examples:
        opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", e["options"]))
        # 把考点/题型拼进文本，让 BM25 关键词检索能按主题命中（如 "Inheritance"）
        # embed/rerank 只取 stem 前 500 字符（超长 stem 会让 onnxruntime CPU 推理异常慢，~1s/条）；
        # payload 里的 stem 仍保留完整，供 few-shot 展示用。
        text = f"{e['knowledge_point']} {e['type']}\n{e['stem'][:500]}\n{opts}"
        docs.append({"qid": _qid(e["stem"]), "text": text, "payload": {
            "kind": "example", "text": text,
            "knowledge_point": e["knowledge_point"], "type": e["type"],
            "difficulty": e["difficulty"], "unit": e["unit"],
            "stem": e["stem"], "options": e["options"],
            "source": e.get("source", "official"),
        }})
    return docs


def build_index(force: bool = False):
    """建索引（幂等：collection 已存在且非 force 则跳过）。"""
    dense, sparse, _ = _models()
    client = _get_client()
    if client.collection_exists(COLLECTION):
        if not force:
            return
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={"dense": models.VectorParams(size=DENSE_DIM, distance=models.Distance.COSINE)},
        sparse_vectors_config={"bm25": models.SparseVectorParams()},
    )
    docs = _docs()
    texts = [d["text"] for d in docs]
    dvecs = list(dense.embed(texts))
    svecs = list(sparse.embed(texts))
    points = [
        models.PointStruct(
            id=d["qid"],
            vector={
                "dense": dv.tolist(),
                "bm25": models.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist()),
            },
            payload=d["payload"],
        )
        for i, (d, dv, sv) in enumerate(zip(docs, dvecs, svecs))
    ]
    client.upsert(collection_name=COLLECTION, points=points)


def _question_doc(q: dict) -> dict:
    """把一道题（dict）转成 (qid, text, payload) 文档，与 _docs 的 example 结构一致。"""
    opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", q.get("options", [])))
    text = f"{q['knowledge_point']} {q['type']}\n{q['stem'][:500]}\n{opts}"
    return {
        "qid": _qid(q["stem"]),
        "text": text,
        "payload": {
            "kind": "example", "text": text,
            "knowledge_point": q["knowledge_point"], "type": q["type"],
            "difficulty": q["difficulty"], "unit": q.get("unit", 0),
            "stem": q["stem"], "options": q.get("options", []),
            "source": q.get("source", "user"),
        },
    }


def add_questions(questions: list[dict]) -> tuple[int, int]:
    """增量入库：embed 新题并 upsert，跳过已在库的 stem（不覆盖已有题）。返回 (新增, 跳过)。"""
    if not questions:
        return 0, 0
    client = _get_client()
    if not client.collection_exists(COLLECTION):
        build_index()
    docs = [_question_doc(q) for q in questions]
    existing = client.retrieve(collection_name=COLLECTION, ids=[d["qid"] for d in docs])
    existing_ids = {p.id for p in existing}
    fresh = [d for d in docs if d["qid"] not in existing_ids]
    if fresh:
        dense, sparse, _ = _models()
        texts = [d["text"] for d in fresh]
        dvecs = list(dense.embed(texts))
        svecs = list(sparse.embed(texts))
        points = [
            models.PointStruct(
                id=d["qid"],
                vector={
                    "dense": dv.tolist(),
                    "bm25": models.SparseVector(indices=sv.indices.tolist(), values=sv.values.tolist()),
                },
                payload=d["payload"],
            )
            for d, dv, sv in zip(fresh, dvecs, svecs)
        ]
        client.upsert(collection_name=COLLECTION, points=points)
    return len(fresh), len(docs) - len(fresh)


def delete_question(stem: str) -> None:
    """按题干删除单题（精确删 point）。"""
    client = _get_client()
    if client.collection_exists(COLLECTION):
        client.delete(collection_name=COLLECTION, points_selector=models.PointIdsList(points=[_qid(stem)]))


def reset_user() -> None:
    """删除所有用户上传的题（按 payload source 过滤），官方基线不动。"""
    client = _get_client()
    if client.collection_exists(COLLECTION):
        client.delete(
            collection_name=COLLECTION,
            points_selector=models.FilterSelector(
                filter=models.Filter(must=[models.FieldCondition(key="source", match=models.MatchValue(value="user"))])
            ),
        )


def _hybrid_search(query_text: str, limit: int = 15) -> list[dict]:
    dense, sparse, _ = _models()
    client = _get_client()
    qd = list(dense.embed([query_text]))[0]
    qs = list(sparse.embed([query_text]))[0]
    res = client.query_points(
        collection_name=COLLECTION,
        prefetch=[
            models.Prefetch(query=qd.tolist(), using="dense", limit=limit),
            models.Prefetch(
                query=models.SparseVector(indices=qs.indices.tolist(), values=qs.values.tolist()),
                using="bm25", limit=limit,
            ),
        ],
        query=models.FusionQuery(fusion=models.Fusion.RRF),
        limit=limit,
        with_payload=True,
    )
    return [p.payload for p in res.points]


def retrieve(request: GenerateRequest, top_k: int = 3) -> dict:
    """混合检索 + 重排，返回 {'examples': [...], 'syllabus': [...]}。"""
    if not _get_client().collection_exists(COLLECTION):
        build_index()
    query_text = f"{request.knowledge_point} {request.question_type} {request.difficulty}"
    candidates = _hybrid_search(query_text, limit=30)
    if not candidates:
        return {"examples": [], "syllabus": []}
    _, _, rerank = _models()
    scores = rerank.predict([(query_text, c["text"]) for c in candidates])
    for c, s in zip(candidates, scores):
        c["score"] = float(s)
    candidates.sort(key=lambda c: c["score"], reverse=True)
    # 按题型过滤：选择题请求只给选择题样例，编程题请求只给编程题样例
    examples = [c for c in candidates
                if c["kind"] == "example" and c.get("type") == request.question_type][:top_k]
    syllabus = [c for c in candidates if c["kind"] == "syllabus"][:3]
    return {"examples": examples, "syllabus": syllabus}
