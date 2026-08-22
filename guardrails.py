"""规则护栏：对生成题目做确定性校验（不调用模型）。

只做结构/格式层面的检查，不做语义判断（答案对不对、解析严不严谨
这些需要 LLM 打分或人工 review，规则做不了）。

用法：
    result = check_response(resp)
    if result.ok:            # 无 error
        ...                  # result.warnings 可提示

约定：选择题 answer 存选项字母（"A"~"E"，AP CSA MCQ 为 5 选项）；编程题(FRQ) answer 存代码/要点。
error 级 → graph 据此重试；warning 级 → 放行但可提示。
"""
from dataclasses import dataclass, field

from schemas import GenerateResponse, Question

CHOICE_LETTERS = "ABCDE"


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _answer_letter(answer: str) -> str | None:
    """从答案里取出第一个 A-E 字母，用于校验选择题答案。"""
    for ch in answer.upper():
        if ch in CHOICE_LETTERS:
            return ch
    return None


def check_question(q: Question) -> CheckResult:
    result = CheckResult()

    # 1. 必填字段非空
    if not q.subject.strip():
        result.errors.append("subject 为空")
    if not q.knowledge_point.strip():
        result.errors.append("考点为空")
    if not q.stem.strip():
        result.errors.append("题干为空")
    if not q.answer.strip():
        result.errors.append("答案为空")
    if not q.explanation.strip():
        result.errors.append("解析为空")

    # 2/3. 题型与选项、答案一致性
    if q.type == "选择题":
        if len(q.options) != 5:
            result.errors.append(f"选择题应有 5 个选项，实际 {len(q.options)} 个")
        letter = _answer_letter(q.answer)
        if letter is None:
            result.errors.append(f"选择题答案 '{q.answer}' 无法识别为选项字母")
        elif CHOICE_LETTERS.index(letter) >= len(q.options):
            result.errors.append(f"答案 '{letter}' 超出选项范围（共 {len(q.options)} 项）")
    else:  # 编程题
        if q.options:
            result.errors.append(f"编程题不应带选项，实际有 {len(q.options)} 个")

    # 4. 编程题评分要点（warning）
    if q.type == "编程题" and not q.marking_points:
        result.warnings.append("编程题未提供评分要点")

    return result


def check_response(resp: GenerateResponse) -> CheckResult:
    """校验整个出题响应，汇总每道题的问题。"""
    result = CheckResult()
    if not resp.questions:
        result.errors.append("未生成任何题目")
        return result
    for i, q in enumerate(resp.questions, 1):
        r = check_question(q)
        result.errors.extend(f"第{i}题: {e}" for e in r.errors)
        result.warnings.extend(f"第{i}题: {w}" for w in r.warnings)
    return result
