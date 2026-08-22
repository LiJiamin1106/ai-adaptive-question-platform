"""CB 官方题源解析入库：把 AP Classroom 官方题（PDF / docx）解析成结构化题目，写入 data/questions.json。

数据源（以 CB 官方为准，见数据源说明）：
  - CB Quiz/SG_M1..M10 quiz（选择题，对应 Unit1-10）
  - SG_Unit1..10 ProgressCheck MCQ（选择题）
  - SG_Unit2..10 ProgressCheck FRQ（编程题）
  - CSA AP ClassRoom MCQ.pdf（选择题，Basic Part 1/2，格式特殊 best-effort）
  - CB刷题/slides/21道选择.docx（选择题，best-effort）

去重：同一份题存在 SG/TB 学生版·教师版、docx/pdf 双格式、挑选版与全量版重叠，
按「规范化 stem」去重兜底，后出现的丢弃。

难度字段先写占位「中等」，由 annotate_difficulty.py 用大模型覆盖。

用法：uv run python pdf_ingest.py
"""
import json
import os
import re
import zipfile

import pymupdf

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT = os.path.join(DATA_DIR, "questions.json")

CB_BASE = r"E:\教学材料\AP计算机科学A\CB\CB题"

# 10 单元标准知识点（英文，与 rag 检索文本、已有 questions.json 一致）
UNIT_KP = {
    1: "Primitive Types",
    2: "Using Objects",
    3: "Boolean Expressions and if Statements",
    4: "Iteration",
    5: "Writing Classes",
    6: "Array",
    7: "ArrayList",
    8: "2D Array",
    9: "Inheritance",
    10: "Recursion",
}

# 页眉页脚（AP Classroom 水印），逐行过滤（大小写不敏感，兼容 "M10 quiz"/"m1 QUIZ" 等）
_FOOTER = re.compile(
    r"^(AP COMPUTER SCIENCE A|Scoring Guide|"
    r"Unit \d+ Progress Check: (MCQ|FRQ)|Page \d+ of \d+|Test Booklet|"
    r"M\d+ Quiz|Basic Part \d+:? ?MCQ)$",
    re.IGNORECASE,
)


def pdf_text(path: str) -> str:
    doc = pymupdf.open(path)
    text = "\n".join(page.get_text() for page in doc)
    doc.close()
    return text


def docx_text(path: str) -> str:
    """docx 提文本：按段落拆，逐段拼 <w:t> run，保留段落边界。"""
    with zipfile.ZipFile(path) as z:
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


def _clean(text: str) -> str:
    lines = [ln for ln in text.split("\n") if not _FOOTER.match(ln.strip())]
    return "\n".join(lines)


def _normalize(s: str) -> str:
    """规范化 stem 作去重键：去掉所有空白。"""
    return re.sub(r"\s+", "", s)


def _parse_mcq_body(body: str, allow_dot: bool = False) -> dict | None:
    """从一道题文本拆出 stem + 5 选项（A-E）。

    allow_dot=True 时兼容「A. 内容」句点格式（Classroom MCQ 用到）；否则只用「(A)」括号格式。
    """
    letters = "ABCDE"
    pos = {L: None for L in letters}
    for L in letters:
        m = re.search(rf"\n\s*\({L}\)\s*", body)
        if m is None and allow_dot:
            m = re.search(rf"\n\s*{L}\.\s", body)
        pos[L] = m.start() if m else None
    if pos["A"] is None:
        return None
    stem = body[:pos["A"]].strip()
    options = []
    for idx, L in enumerate(letters):
        s = pos[L]
        if s is None:
            break
        e = None
        for nxt in letters[idx + 1:]:
            if pos[nxt] is not None:
                e = pos[nxt]
                break
        opt = body[s:e].strip()
        # 去掉选项标记（(A) 或 A.）及紧跟的空白
        opt = re.sub(rf"^(?:\({L}\)|{L}\.)\s*", "", opt).strip()
        # 选项内容里也可能混入页脚行（尤其最后一个选项），逐行过滤
        opt = "\n".join(ln for ln in opt.split("\n") if not _FOOTER.match(ln.strip())).strip()
        options.append(opt)
    if not stem or len(options) != 5:
        return None
    return {"stem": stem, "options": options}


def _split_by_number(text: str, pattern: str) -> list[tuple[int, int]]:
    """按题号行切分，返回 [(start, end), ...]，题号行被排除在题干之外。"""
    matches = list(re.finditer(pattern, text))
    spans = []
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        spans.append((start, end))
    return spans


def parse_mcq_pdf(text: str, unit: int, knowledge_point: str) -> list[dict]:
    """PDF 选择题：题号「\n数字.\n」+ 选项 (A)-(E)。"""
    text = "\n" + _clean(text)  # 前导换行，保证第一题也能被匹配
    spans = _split_by_number(text, r"\n(\d{1,2})\.\s*\n")
    out = []
    for start, end in spans:
        q = _parse_mcq_body(text[start:end])
        if q:
            q.update({"unit": unit, "knowledge_point": knowledge_point,
                      "type": "选择题", "difficulty": "中等"})
            out.append(q)
    return out


def parse_mcq_docx(text: str, unit: int, knowledge_point: str) -> list[dict]:
    """docx 选择题：题号「数字.」可能独立成段也可能与题干同行，选项 (A)-(E)。"""
    text = "\n" + _clean(text)
    # 题号行：数字. 后面跟换行 或 直接跟非空字符（如 1.Consider...）
    spans = _split_by_number(text, r"\n(\d{1,2})\.\s*")
    out = []
    for start, end in spans:
        q = _parse_mcq_body(text[start:end])
        if q:
            q.update({"unit": unit, "knowledge_point": knowledge_point,
                      "type": "选择题", "difficulty": "中等"})
            out.append(q)
    return out


def parse_classroom_mcq(text: str) -> list[dict]:
    """Classroom MCQ：Basic Part 1/2，题号「数字.」或「数字」单独一行，选项 (A) 或 A. 混用。"""
    text = "\n" + _clean(text)
    # 去掉 section 标题（Basic Part 1/2: MCQ）
    text = re.sub(r"\n\s*Basic Part \d+:?\s*MCQ\s*", "\n", text)
    spans = _split_by_number(text, r"\n(\d{1,3})\.?\s*\n")
    out = []
    for start, end in spans:
        # Classroom MCQ 的选项可能是句点格式，打开 allow_dot
        q = _parse_mcq_body(text[start:end], allow_dot=True)
        if q:
            q.update({"unit": 0, "knowledge_point": "Fundamentals",
                      "type": "选择题", "difficulty": "中等"})
            out.append(q)
    return out


def parse_frq(text: str, unit: int, knowledge_point: str) -> list[dict]:
    """FRQ：去掉通用说明与学生指导语，按「\n数字.\n」切大题，整题（含 a-f 子题）作一条 stem。"""
    text = "\n" + _clean(text)
    # 去掉通用 FRQ 说明块（SHOW ALL YOUR WORK ... will not receive full credit.）
    text = re.sub(r"SHOW ALL YOUR WORK\..*?will not receive full credit\.", "", text, flags=re.S)
    # 去掉学生指导语（SG 版有，TB 版无——去掉后两者 stem 一致，便于去重）
    text = re.sub(r"Please respond on separate paper, following directions from your teacher\.?", "", text)
    spans = _split_by_number(text, r"\n(\d{1,2})\.\s*\n")
    out = []
    for start, end in spans:
        stem = text[start:end].strip()
        stem = re.sub(r"\s{3,}", "\n", stem)  # 压缩多余空行
        if len(stem) > 100:
            out.append({"unit": unit, "knowledge_point": knowledge_point,
                        "type": "编程题", "difficulty": "中等", "stem": stem, "options": []})
    return out


def build_sources() -> list[tuple[str, int, str, str]]:
    """扫描 CB 目录，返回 [(path, unit, knowledge_point, kind)]，kind ∈ mcq_pdf/frq/classroom/docx。"""
    sources = []
    quiz_dir = os.path.join(CB_BASE, "CB Quiz")
    for f in sorted(os.listdir(quiz_dir)):
        m = re.match(r"SG_M(\d{1,2})[qQ]uiz", f)
        if m and f.lower().endswith(".pdf"):
            u = int(m.group(1))
            sources.append((os.path.join(quiz_dir, f), u, UNIT_KP[u], "mcq_pdf"))
    for f in sorted(os.listdir(CB_BASE)):
        m = re.match(r"SG_Unit(\d{1,2})ProgressCheckMCQ", f)
        if m and f.lower().endswith(".pdf"):
            u = int(m.group(1))
            sources.append((os.path.join(CB_BASE, f), u, UNIT_KP[u], "mcq_pdf"))
    for f in sorted(os.listdir(CB_BASE)):
        m = re.match(r"SG_Unit(\d{1,2})ProgressCheckFRQ", f)
        if m and f.lower().endswith(".pdf"):
            u = int(m.group(1))
            sources.append((os.path.join(CB_BASE, f), u, UNIT_KP[u], "frq"))
    classroom = os.path.join(CB_BASE, "CSA AP ClassRoom MCQ.pdf")
    if os.path.exists(classroom):
        sources.append((classroom, 0, "Fundamentals", "classroom"))
    docx21 = os.path.join(CB_BASE, "CB刷题", "slides", "21道选择.docx")
    if os.path.exists(docx21):
        sources.append((docx21, 0, "Fundamentals", "docx"))
    return sources


def ingest() -> list[dict]:
    all_q = []
    seen = set()
    for path, unit, kp, kind in build_sources():
        if not os.path.exists(path):
            print(f"[跳过] 不存在: {path}")
            continue
        try:
            if kind == "docx":
                text = docx_text(path)
            else:
                text = pdf_text(path)
        except Exception as e:
            print(f"[跳过] 提取失败 {os.path.basename(path)}: {e}")
            continue
        if kind == "mcq_pdf":
            qs = parse_mcq_pdf(text, unit, kp)
        elif kind == "docx":
            qs = parse_mcq_docx(text, unit, kp)
        elif kind == "classroom":
            qs = parse_classroom_mcq(text)
        else:  # frq
            qs = parse_frq(text, unit, kp)
        # 去重
        added = 0
        for q in qs:
            key = _normalize(q["stem"])
            if key in seen:
                continue
            seen.add(key)
            all_q.append(q)
            added += 1
        print(f"{os.path.basename(path)}: 解析 {len(qs)} 题，去重后 +{added}")
    return all_q


if __name__ == "__main__":
    qs = ingest()
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(qs, f, ensure_ascii=False, indent=2)
    print(f"\n共 {len(qs)} 题 -> {OUT}")
