"""LangGraph 编排：retrieve → generate → validate（校验不过自动重试）。

把 rag / llm / guardrails 串成一张图：
  START → retrieve → generate → validate → (有 error 且未超次数 ? generate : END)
"""
import re
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import guardrails
import llm
import rag
from schemas import GenerateRequest, GenerateResponse, PaperRequest, PaperResponse

MAX_RETRIES = 2

# 选项标记：行首的 A. / (A) / A)
_OPT_MARK = re.compile(r"\n\s*[\(（]?([A-E])[\.\)）]\s*")
_OPT_PREFIX = re.compile(r"^[\(（]?[A-E][\.\)）]\s*")


def _clean_questions(questions):
    """清洗生成的选择题：options 去字母前缀 + stem 剥离选项块（防止选项出现两遍）。

    LLM 常把完整题目（含选项）写进 stem，又单独填 options 数组，导致选项出现两遍。
    这里用确定性的后处理剥离 stem 末尾的选项块，不依赖 prompt 自觉。
    """
    for q in questions:
        if q.type != "选择题":
            continue
        # options 去字母前缀（兜底）
        q.options = [_OPT_PREFIX.sub("", o).strip() for o in q.options]
        # stem 剥离选项块：找行首 A 标记，且后面紧跟 B/C/D/E 连续标记，则截断
        marks = list(_OPT_MARK.finditer(q.stem))
        for i, m in enumerate(marks):
            if m.group(1) == "A":
                seq = [mm.group(1) for mm in marks[i + 1:i + 5]]
                if seq[:4] == ["B", "C", "D", "E"]:
                    q.stem = q.stem[:m.start()].rstrip()
                    break
    return questions


class State(TypedDict, total=False):
    request: GenerateRequest
    examples: list
    syllabus: list
    questions: list
    errors: list
    warnings: list
    retries: int


def _retrieve_node(state: State) -> dict:
    result = rag.retrieve(state["request"])
    return {"examples": result["examples"], "syllabus": result["syllabus"]}


def _build_messages(state: State) -> list[dict]:
    request = state["request"]
    sys_parts = [
        "你是一名 AP Computer Science A 出题老师，出题严谨、答案正确、解析分步清晰。",
        "Java 代码用 ``` 代码块表示。选择题必须是 5 个选项（A-E），只有一个正确答案。",
        "选项（options）数组只填选项内容，不要含 A./B. 等字母前缀；题干（stem）严格到问题句（如 'What is printed...?'）为止，绝对不要写任何 'A. xxx B. xxx' 形式的选项文本，选项只能出现在 options 数组里。",
        "严格对齐考点，不要超出考点范围，术语与 AP CSA 保持一致。",
        "每道题必须完整给出三样：标准答案（选择题填选项字母，如 A）、"
        "分步解析（逐步说明推导过程）、评分要点（marking_points 数组）。",
    ]
    examples = state.get("examples", [])
    if examples:
        sys_parts.append("以下是同考点的真题样例，请模仿其风格、措辞和难度：")
        for i, e in enumerate(examples, 1):
            opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", e["options"]))
            sys_parts.append(f"[样例{i}]\n{e['stem']}\n{opts}")
    system = "\n\n".join(sys_parts)
    count = request.count
    if count > 1:
        task = f"请出 {count} 道「{request.knowledge_point}」考点、「{request.question_type}」题型、「{request.difficulty}」难度的题。"
    else:
        task = f"请出一道「{request.knowledge_point}」考点、「{request.question_type}」题型、「{request.difficulty}」难度的题。"
    return [{"role": "system", "content": system}, {"role": "user", "content": task}]


def _generate_node(state: State) -> dict:
    messages = _build_messages(state)
    resp = llm.generate_questions(messages)
    return {
        "questions": resp.questions,
        "retries": state.get("retries", 0) + 1,
    }


def _validate_node(state: State) -> dict:
    resp = GenerateResponse(questions=state["questions"])
    result = guardrails.check_response(resp)
    return {"errors": result.errors, "warnings": result.warnings}


def _should_retry(state: State) -> str:
    if state.get("errors") and state.get("retries", 0) < MAX_RETRIES:
        return "generate"
    return "done"


_graph = StateGraph(State)
_graph.add_node("retrieve", _retrieve_node)
_graph.add_node("generate", _generate_node)
_graph.add_node("validate", _validate_node)
_graph.add_edge(START, "retrieve")
_graph.add_edge("retrieve", "generate")
_graph.add_edge("generate", "validate")
_graph.add_conditional_edges("validate", _should_retry, {"generate": "generate", "done": END})
_compiled = _graph.compile()


def generate(request: GenerateRequest) -> GenerateResponse:
    """出题入口：跑完 retrieve → generate → validate（含自动重试），返回题目。"""
    result = _compiled.invoke({"request": request, "retries": 0})
    return GenerateResponse(questions=_clean_questions(result["questions"]))


def _paper_messages(knowledge_point: str, question_type: str, difficulty: str, count: int,
                    examples: list, already_generated: list) -> list[dict]:
    """构造出卷的 messages：真题样例 + 已生成题目（防雷同）。"""
    sys_parts = [
        "你是一名 AP Computer Science A 出题老师，出题严谨、答案正确、解析分步清晰。",
        "Java 代码用 ``` 代码块表示。选择题必须是 5 个选项（A-E），只有一个正确答案。",
        "选项（options）数组只填选项内容，不要含 A./B. 等字母前缀；题干（stem）严格到问题句（如 'What is printed...?'）为止，绝对不要写任何 'A. xxx B. xxx' 形式的选项文本，选项只能出现在 options 数组里。",
        "严格对齐考点，不要超出考点范围，术语与 AP CSA 保持一致。",
        "每道题必须完整给出三样：标准答案（选择题填选项字母，如 A）、"
        "分步解析（逐步说明推导过程）、评分要点（marking_points 数组）。",
    ]
    if examples:
        sys_parts.append("以下是同考点的真题样例，请模仿其风格、措辞和难度：")
        for i, e in enumerate(examples, 1):
            opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", e["options"]))
            sys_parts.append(f"[样例{i}]\n{e['stem']}\n{opts}")
    if already_generated:
        sys_parts.append("以下是本卷已生成的题目，请务必避免雷同（不要只换数字/变量名）：")
        for i, q in enumerate(already_generated, 1):
            opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", q.options))
            sys_parts.append(f"[已出{i}] {q.knowledge_point}\n{q.stem}\n{opts}")
    system = "\n\n".join(sys_parts)
    task = f"请出 {count} 道「{knowledge_point}」考点、「{question_type}」题型、「{difficulty}」难度的题。"
    return [{"role": "system", "content": system}, {"role": "user", "content": task}]


def generate_paper(request: PaperRequest) -> PaperResponse:
    """出卷：按规格逐项生成（单元型 = 单一知识点；综合型 = 多知识点组合）。

    同一知识点出多道、跨知识点出卷时，把已生成的题作为防重复上下文，
    分批生成（每批 ≤5）保证质量。
    """
    all_q = []
    for spec in request.specs:
        if spec.count <= 0:
            continue
        req = GenerateRequest(
            subject="AP Computer Science A",
            knowledge_point=spec.knowledge_point,
            question_type=spec.question_type,
            difficulty=spec.difficulty,
            count=1,  # count 仅用于检索 query，实际出题数量由分批控制
        )
        examples = rag.retrieve(req)["examples"]
        remaining = spec.count
        while remaining > 0:
            batch = min(remaining, 5)
            messages = _paper_messages(spec.knowledge_point, spec.question_type,
                                       spec.difficulty, batch, examples, all_q)
            resp = llm.generate_questions(messages)
            all_q.extend(resp.questions)
            remaining -= batch
    return PaperResponse(questions=_clean_questions(all_q))
