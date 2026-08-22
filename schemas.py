"""数据契约：出题 / 题目 / 生成请求与响应。

这是整个 demo 的"共同语言"——前端渲染、LLM 结构化输出、规则护栏、
RAG 检索，全部基于这些字段，所以先定清楚。

AP CSA 是编程科目，stem / answer / explanation 里可含 Java 代码
（用 ``` ``` 代码块或行内 `` 标注），不涉及 LaTeX 数学公式。
"""
from typing import List, Literal

from pydantic import BaseModel, Field

# 难度三档；题型对应 AP CSA 考试：选择题(MCQ) + 编程题(FRQ，写 Java 代码)
Difficulty = Literal["基础", "中等", "较难"]
QuestionType = Literal["选择题", "编程题"]


class Question(BaseModel):
    """一道完整的题目 + 答案 + 分步解析 + 评分要点。"""

    subject: str = Field(description="科目，如 AP Computer Science A")
    knowledge_point: str = Field(description="考点，如 Inheritance / ArrayLists")
    type: QuestionType = Field(description="题型")
    difficulty: Difficulty = Field(description="难度")
    stem: str = Field(description="题干，可含 Java 代码（不含选项文本，选项单独放 options）")
    options: List[str] = Field(default_factory=list, description="选择题选项（只填内容，不含 A./B. 字母前缀）；编程题留空")
    answer: str = Field(description="标准答案（选择题为选项字母，编程题为代码/要点）")
    explanation: str = Field(description="分步解析，可含 Java 代码")
    marking_points: List[str] = Field(default_factory=list, description="评分要点 / 答案要点")


class GenerateRequest(BaseModel):
    """一次出题请求。"""

    subject: str = Field(description="科目")
    knowledge_point: str = Field(description="考点，如 Inheritance")
    question_type: QuestionType = Field(description="题型")
    difficulty: Difficulty = Field(description="难度")
    count: int = Field(default=1, ge=1, le=5, description="生成题数（1~5）")


class GenerateResponse(BaseModel):
    """出题结果。"""

    questions: List[Question] = Field(description="生成的题目列表")


class DifficultyAnnotations(BaseModel):
    """一批题目的难度标注结果（按输入顺序一一对应）。"""

    difficulties: List[Difficulty] = Field(description="按输入顺序返回每题难度（基础/中等/较难）")


class ParsedQuestions(BaseModel):
    """从文档解析出的一组题目（含 LLM 补全的答案/解析/知识点/难度）。"""

    questions: List[Question] = Field(description="解析出的题目列表")


class PaperSpec(BaseModel):
    """出卷规格：某知识点某题型出几道（count 可为 0 表示不出）。"""

    knowledge_point: str = Field(description="考点")
    question_type: QuestionType = Field(description="题型")
    count: int = Field(default=1, ge=0, le=20, description="该题型出几道（0 表示不出）")
    difficulty: Difficulty = Field(description="难度")


class PaperRequest(BaseModel):
    """出卷请求：一组规格（单元型 = 单一知识点多题型；综合型 = 多知识点自由组合）。"""

    specs: List[PaperSpec] = Field(description="出题规格列表")


class PaperResponse(BaseModel):
    """出卷结果。"""

    questions: List[Question] = Field(description="整卷题目列表")


class KnowledgePointAnnotations(BaseModel):
    """一批题目的考点标注结果（按输入顺序一一对应，值须来自候选清单）。"""

    knowledge_points: List[str] = Field(description="按输入顺序返回每题考点")


class ExportRequest(BaseModel):
    """导出请求：一组题目（出题篮）。"""

    questions: List[Question] = Field(description="要导出的题目列表")
