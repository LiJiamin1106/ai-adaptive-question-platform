"""LangGraph 编排：retrieve → generate → validate（校验不过自动重试）。

把 rag / llm / guardrails 串成一张图：
  START → retrieve → generate → validate → (有 error 且未超次数 ? generate : END)
"""
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

import guardrails
import llm
import rag
from schemas import GenerateRequest, GenerateResponse

MAX_RETRIES = 2


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
    return GenerateResponse(questions=result["questions"])
