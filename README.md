# AP CSA 出题助手（demo）

教师向的 AP Computer Science A（Java）出题辅助工具：**RAG 检索真题 → DeepSeek 生成 → 规则护栏校验**。

## 技术栈

- **FastAPI** + **LangGraph** 编排（retrieve → generate → validate，自动重试）
- **langchain-deepseek** 调 `deepseek-v4-flash`（结构化输出，已关思考模式）
- **Qdrant**（本地落盘）+ **fastembed**（dense + BM25）+ **sentence-transformers**（rerank）
- **PyMuPDF** + **RapidOCR**（PDF 解析入库）
- 依赖管理用 **uv**，Python 3.11

## 快速开始

```bash
# 1. 配置 API Key（.env 里已留好位置）
#    DEEPSEEK_API_KEY=sk-xxx

# 2. 安装依赖
uv sync

# 3.（可选）重新解析真题 PDF 入库
uv run python pdf_ingest.py

# 4. 启动服务（首次会下载 embedding/rerank 模型，走 HF 镜像）
uv run uvicorn main:app --reload

# 5. 浏览器打开
#    http://localhost:8000
```

## 目录结构

```
main.py          FastAPI 入口（/generate + / 前端）
graph.py         LangGraph 编排（检索→生成→校验→重试）
rag.py           Qdrant 混合检索 + rerank
llm.py           DeepSeek 调用（with_structured_output）
guardrails.py    规则护栏（5 选项 A-E、字段完整、题型一致）
schemas.py       数据契约（Question / GenerateRequest / GenerateResponse）
pdf_ingest.py    PDF 解析入库（文本型 MCQ/FRQ + 扫描版 OCR）
data/            syllabus.json + examples.json + questions.json（语料）
index.html       教师工作台前端
```

## 说明

- 语料：官方 10 单元考纲 + 50 道选择题真题 + 4 道编程题真题（来自 AP Classroom ProgressCheck，文本型）。
- 扫描版历年真题（1999–2020）已支持 OCR（`pdf_ingest.py` 的 `ocr_text`），但质量一般，默认未入库。
- 生产化方向：接入 MySQL（题目/作答）、Redis（缓存）、Docker 化 Qdrant + 服务。
