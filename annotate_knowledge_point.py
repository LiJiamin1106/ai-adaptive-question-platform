"""大模型标注考点：读 questions.json，按单元从 knowledge_points.json 取候选考点，批量标注，写回 knowledge_point 字段。

把 knowledge_point 从「单元标题」（如 ArrayList）细化为「具体考点」（如 get method）。
Fundamentals（跨单元）的题用全量候选，由模型跨单元归类。

用法：uv run python annotate_knowledge_point.py
"""
import json
import os
from collections import Counter, defaultdict

from llm import annotate_knowledge_point

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(BASE_DIR, "data", "questions.json")
KP_PATH = os.path.join(BASE_DIR, "data", "knowledge_points.json")

BATCH = 20


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    with open(QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)
    with open(KP_PATH, encoding="utf-8") as f:
        kp_map = json.load(f)
    all_candidates = [kp for kps in kp_map.values() for kp in kps]

    # 按现有 knowledge_point（单元标题）分组
    groups = defaultdict(list)
    for q in questions:
        groups[q["knowledge_point"]].append(q)

    total = len(questions)
    done = 0
    for unit_title, qs in groups.items():
        candidates = kp_map.get(unit_title, all_candidates)
        for batch in _batches(qs, BATCH):
            kps = annotate_knowledge_point(batch, candidates)
            for q, kp in zip(batch, kps):
                q["knowledge_point"] = kp
            done += len(batch)
            with open(QUESTIONS, "w", encoding="utf-8") as f:
                json.dump(questions, f, ensure_ascii=False, indent=2)
            print(f"[{done}/{total}] {unit_title} 本批 {len(batch)} 题", flush=True)

    dist = Counter(q["knowledge_point"] for q in questions)
    print(f"\n完成 {total} 题。考点分布:")
    for kp, c in sorted(dist.items(), key=lambda t: -t[1]):
        print(f"  {kp}: {c}")


if __name__ == "__main__":
    main()
