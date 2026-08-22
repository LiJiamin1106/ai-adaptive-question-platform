"""大模型标注难度：读 data/questions.json，批量调 DeepSeek 判断「基础/中等/较难」，写回 difficulty 字段。

选择题每批 20 题、编程题每批 2 题（stem 长），每批标注后立即写回（中断可保留进度）。
解析与标注解耦：改了难度 rubric 或想换模型，只需重跑本脚本，无需重解析。

用法：uv run python annotate_difficulty.py
"""
import json
import os
from collections import Counter

from llm import annotate_difficulty

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = os.path.join(BASE_DIR, "data", "questions.json")

MCQ_BATCH = 20
FRQ_BATCH = 2


def _batches(items, size):
    for i in range(0, len(items), size):
        yield items[i:i + size]


def main():
    with open(QUESTIONS, encoding="utf-8") as f:
        questions = json.load(f)

    mcq = [q for q in questions if q["type"] == "选择题"]
    frq = [q for q in questions if q["type"] == "编程题"]
    total = len(questions)
    done = 0

    for group, size in [(mcq, MCQ_BATCH), (frq, FRQ_BATCH)]:
        for batch in _batches(group, size):
            diffs = annotate_difficulty(batch)
            for q, d in zip(batch, diffs):
                q["difficulty"] = d
            done += len(batch)
            with open(QUESTIONS, "w", encoding="utf-8") as f:
                json.dump(questions, f, ensure_ascii=False, indent=2)
            print(f"[{done}/{total}] {batch[0]['type']} 本批 {len(batch)} 题")

    dist = Counter(q["difficulty"] for q in questions)
    print(f"\n完成 {total} 题。难度分布: {dict(dist)}")


if __name__ == "__main__":
    main()
