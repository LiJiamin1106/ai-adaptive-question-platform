"""FastAPI 入口：教师出题工作台。

启动：uv run uvicorn main:app --reload
然后浏览器打开 http://localhost:8000

能力：
  - POST /generate        出题（RAG 检索 + LLM 生成 + 护栏）
  - POST /upload          上传资料（PDF/docx）→ LLM 解析 → 增量入库
  - GET  /questions       列出题目（?source=user 看用户上传的题）
  - DELETE /questions/{id} 删除单道用户题（官方题不可删）
  - POST /reset           清空所有用户题，回到官方基线
"""
import io
import json
import os
import re
import zipfile
from contextlib import asynccontextmanager

import pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response

import rag
from export import build_paper_docx
from graph import generate, generate_paper
from llm import parse_questions
from schemas import ExportRequest, GenerateRequest, GenerateResponse, PaperRequest, PaperResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS_PATH = os.path.join(BASE_DIR, "data", "questions.json")

# 上传文档文本上限（超过提示拆分，避免撑爆 LLM context）
MAX_TEXT_CHARS = 15000


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时建 RAG 索引（幂等，已存在则跳过；首次会下载模型，较慢）
    rag.build_index()
    yield


app = FastAPI(title="AP CSA 出题助手", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _extract_text(filename: str, content: bytes) -> str:
    """从上传文件的字节内容抽取纯文本（复用 pdf_ingest 的解析逻辑，但接受 bytes）。"""
    name = (filename or "").lower()
    if name.endswith(".pdf"):
        doc = pymupdf.open(stream=content, filetype="pdf")
        try:
            return "\n".join(page.get_text() for page in doc)
        finally:
            doc.close()
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(content)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "ignore")
        lines = []
        for para in xml.split("</w:p>"):
            runs = re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S)
            txt = "".join(runs)
            txt = (txt.replace("&amp;", "&").replace("&lt;", "<")
                      .replace("&gt;", ">").replace("&quot;", '"').replace("&#39;", "'"))
            if txt.strip():
                lines.append(txt)
        return "\n".join(lines)
    raise HTTPException(400, "仅支持 PDF / docx 文件")


def _load_questions() -> list[dict]:
    with open(QUESTIONS_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_questions(questions: list[dict]) -> None:
    with open(QUESTIONS_PATH, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)


@app.post("/generate", response_model=GenerateResponse)
def generate_questions(req: GenerateRequest) -> GenerateResponse:
    """生成题目：RAG 检索 + LLM 生成 + 护栏校验（含自动重试）。"""
    return generate(req)


@app.post("/assemble_paper", response_model=PaperResponse)
def assemble_paper(req: PaperRequest) -> PaperResponse:
    """出卷：单元型（单一知识点多题型）或综合型（多知识点自由组合）。"""
    return generate_paper(req)


@app.post("/upload")
async def upload(file: UploadFile = File(...)) -> dict:
    """上传资料：抽文本 → LLM 解析成题目 → 标 source=user → 写库 + 增量索引。"""
    filename = file.filename or ""
    content = await file.read()
    text = _extract_text(filename, content)
    if not text.strip():
        raise HTTPException(400, "未能从文档中提取文本（可能是扫描版 PDF，暂不支持）")
    if len(text) > MAX_TEXT_CHARS:
        raise HTTPException(413, f"文档文本过长（{len(text)} 字符），请拆分后上传（上限 {MAX_TEXT_CHARS}）")

    parsed = parse_questions(text)
    user_qs = [q.model_dump() for q in parsed]
    for q in user_qs:
        q["source"] = "user"
        q["unit"] = q.get("unit", 0)  # 跨单元/未指定，检索按 knowledge_point 不依赖 unit

    all_q = _load_questions()
    all_q.extend(user_qs)
    _save_questions(all_q)

    added, skipped = rag.add_questions(user_qs)
    return {"parsed": len(user_qs), "added": added, "skipped": skipped, "questions": user_qs}


@app.get("/questions")
def list_questions(source: str = "user") -> dict:
    """列出题目（默认只列用户上传的，治理面板用）。"""
    all_q = _load_questions()
    if source:
        all_q = [q for q in all_q if q.get("source") == source]
    for q in all_q:
        q["id"] = rag._qid(q["stem"])
    return {"questions": all_q, "count": len(all_q)}


@app.delete("/questions/{qid}")
def delete_question(qid: str) -> dict:
    """删除单道用户题（按稳定 id）。官方题不可删。"""
    all_q = _load_questions()
    target = None
    kept = []
    for q in all_q:
        if q.get("source") == "user" and rag._qid(q["stem"]) == qid:
            target = q
        else:
            kept.append(q)
    if target is None:
        raise HTTPException(404, "未找到该用户题（或该题不是用户上传，不可删）")
    _save_questions(kept)
    rag.delete_question(target["stem"])
    return {"deleted": 1}


@app.post("/reset")
def reset() -> dict:
    """清空所有用户上传的题，回到官方基线（官方题不可动）。"""
    all_q = _load_questions()
    official = [q for q in all_q if q.get("source") != "user"]
    removed = len(all_q) - len(official)
    _save_questions(official)
    rag.reset_user()
    return {"removed": removed, "remaining": len(official)}


@app.post("/export")
def export_questions(req: ExportRequest) -> Response:
    """导出成卷：把题目列表渲染成 Word（.docx），题目卷 + 答案卷分页。"""
    docx = build_paper_docx(req.questions)
    return Response(
        content=docx,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": "attachment; filename=paper.docx"},
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/knowledge_points")
def knowledge_points() -> dict:
    """返回知识点清单 {单元标题: [考点列表]}，供前端级联选择。"""
    with open(os.path.join(BASE_DIR, "data", "knowledge_points.json"), encoding="utf-8") as f:
        return json.load(f)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    with open(os.path.join(BASE_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()
