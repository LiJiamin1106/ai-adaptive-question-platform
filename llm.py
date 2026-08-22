"""DeepSeek 调用封装：ChatDeepSeek + with_structured_output。

用 langchain-deepseek 的 ChatDeepSeek 调 deepseek-v4-flash，
通过 with_structured_output() 绑定 schemas.GenerateResponse，
让模型直接返回通过 Pydantic 校验的结构。

注意：DeepSeek V4 默认开启思考模式，而思考模式不支持强制 tool_choice
（with_structured_output 底层依赖它），所以用 extra_body 显式关闭思考模式。

API Key 从 .env 读取（DEEPSEEK_API_KEY），由 python-dotenv 加载。
"""
import os

from dotenv import load_dotenv
from langchain_deepseek import ChatDeepSeek

from schemas import DifficultyAnnotations, GenerateResponse, ParsedQuestions

load_dotenv()

MODEL_NAME = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip()

if not API_KEY:
    raise RuntimeError("缺少 DEEPSEEK_API_KEY：请在 .env 里填入你的 DeepSeek API Key 后再运行")

_llm = ChatDeepSeek(
    model_name=MODEL_NAME,
    api_key=API_KEY,
    temperature=0.7,  # 出题需要多样性；已关闭思考模式，故 temperature 生效
    extra_body={"thinking": {"type": "disabled"}},  # 关闭思考模式，才能用强制 tool_choice
)

# 结构化输出：模型按 GenerateResponse 的 JSON schema 返回
_structured_llm = _llm.with_structured_output(GenerateResponse)


def generate_questions(messages: list[dict], max_retries: int = 2) -> GenerateResponse:
    """调模型生成题目，返回通过 Pydantic 校验的 GenerateResponse。

    messages: 对话消息列表，如
        [{"role": "system", "content": "你是出题老师..."},
         {"role": "user", "content": "请出一道..."}]

    结构化输出偶发失败（模型未返回工具调用或解析失败）时自动重试。
    """
    last_err = None
    for _ in range(max_retries + 1):
        try:
            resp = _structured_llm.invoke(messages)
            if resp is not None:
                return resp
            last_err = "模型未返回工具调用"
        except Exception as e:  # 解析/校验失败，重试
            last_err = e
    raise RuntimeError(f"结构化生成失败（重试 {max_retries} 次后仍失败）: {last_err}")


_DIFFICULTY_RUBRIC = (
    "AP CSA 题目难度三档，按以下标准判断：\n"
    "- 基础：单一概念直接应用（变量/类型、算术运算、单行输出、简单 if 判断）。\n"
    "- 中等：需要理解+推理（字符串/数组方法、单层循环、简单类设计、简单继承）。\n"
    "- 较难：多概念综合、嵌套循环、继承多态、递归、需手推多步代码/追踪多变量。\n"
)

_annotation_llm = _llm.with_structured_output(DifficultyAnnotations)


def annotate_difficulty(batch: list[dict], max_retries: int = 2) -> list[str]:
    """批量标注难度。batch: [{stem, options, knowledge_point}, ...] → 返回按顺序对应的难度列表。

    一次调用标一批，减少 API 调用次数；结构化输出偶发失败时自动重试。
    """
    lines = []
    for i, q in enumerate(batch, 1):
        opts = "\n".join(f"{c}. {o}" for c, o in zip("ABCDE", q["options"]))
        body = q["stem"] + (f"\n{opts}" if opts else "\n（编程题，无选项）")
        lines.append(f"[{i}] 考点 {q['knowledge_point']}\n{body}")
    user = "请按顺序判断下面每道题的难度，返回与题号一一对应的 difficulties 数组：\n\n" + "\n\n".join(lines)
    messages = [
        {"role": "system", "content": "你是 AP CSA 出题难度标注助手。" + _DIFFICULTY_RUBRIC
                                      + "只返回 difficulties 数组，长度必须与题目数量一致。"},
        {"role": "user", "content": user},
    ]
    last_err = None
    for _ in range(max_retries + 1):
        try:
            resp = _annotation_llm.invoke(messages)
            if resp is not None and len(resp.difficulties) == len(batch):
                return resp.difficulties
            last_err = "模型未返回工具调用或数量不匹配"
        except Exception as e:
            last_err = e
    raise RuntimeError(f"难度标注失败（重试 {max_retries} 次后仍失败）: {last_err}")


_parse_llm = _llm.with_structured_output(ParsedQuestions)


def parse_questions(text: str, max_retries: int = 2) -> list:
    """从文档文本解析出题目列表（LLM 补全答案/解析/知识点/难度）。

    text: 上传文档抽取出的纯文本（可能含多道题）。返回 list[Question]（已通过 Pydantic 校验）。
    """
    system = (
        "你是 AP Computer Science A 出题老师。从给定文档中提取所有题目，逐题结构化输出。\n"
        "要求：\n"
        "- subject 固定填 'AP Computer Science A'。\n"
        "- type：选择题（5 个选项 A-E，只有一个正确答案）或 编程题（写 Java 代码）。\n"
        "- knowledge_point 从 AP CSA 标准考点选：Primitive Types / Using Objects / "
        "Boolean Expressions and if Statements / Iteration / Writing Classes / Array / "
        "ArrayList / 2D Array / Inheritance / Recursion。\n"
        "- difficulty：基础 / 中等 / 较难。\n"
        "- options：选择题填 5 项，编程题留空数组。\n"
        "- 若文档没给答案，据题目补全正确答案（选择题填选项字母、编程题填代码/要点）、"
        "分步解析 explanation、评分要点 marking_points。\n"
        "- Java 代码用 ``` 代码块或行内 `` 表示。\n"
        "如果文档里没有题目，返回空 questions 数组。"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": f"以下是要解析的文档内容：\n\n{text}"},
    ]
    last_err = None
    for _ in range(max_retries + 1):
        try:
            resp = _parse_llm.invoke(messages)
            if resp is not None:
                return resp.questions
            last_err = "模型未返回工具调用"
        except Exception as e:
            last_err = e
    raise RuntimeError(f"文档解析失败（重试 {max_retries} 次后仍失败）: {last_err}")
