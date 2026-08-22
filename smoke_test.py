"""冒烟测试：验证 DeepSeek 调用 + 结构化输出端到端可用。

用法：uv run python smoke_test.py
"""
from llm import generate_questions

messages = [
    {
        "role": "system",
        "content": (
            "你是一名资深数学出题老师，出题严谨、答案正确、解析分步清晰。"
            "公式一律用 LaTeX（如 $x^2-3x+2=0$）。"
        ),
    },
    {
        "role": "user",
        "content": (
            "请出一道「一元二次方程」考点、「选择题」题型、「基础」难度的题，"
            "含四个选项、唯一正确答案和分步解析。"
        ),
    },
]

result = generate_questions(messages)
for q in result.questions:
    print(q.model_dump_json(indent=2))
