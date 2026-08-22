"""临时调试：打印 DeepSeek 返回的原始内容。"""
from llm import _llm

SYSTEM = (
    "你是一名资深数学出题老师，出题严谨、答案正确、解析分步清晰。"
    "公式一律用 LaTeX（如 $x^2-3x+2=0$）。"
    "你必须只输出一个 JSON 对象，结构如下："
    '{"questions": [{"subject": "数学", "knowledge_point": "考点", '
    '"type": "选择题|填空题|简答题", "difficulty": "基础|中等|较难", '
    '"stem": "题干", "options": ["选项A", "选项B", "选项C", "选项D"], '
    '"answer": "答案", "explanation": "分步解析", "marking_points": ["评分要点"]}]}'
    "选择题必须填 4 个 options 且只有一个正确答案；填空题/简答题 options 留空数组 []。"
)

messages = [
    {"role": "system", "content": SYSTEM},
    {"role": "user", "content": "请出一道「一元二次方程」考点、「选择题」题型、「基础」难度的题。"},
]

resp = _llm.invoke(messages)
print("=== RAW CONTENT ===")
print(repr(resp.content))
