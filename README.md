# AP CSA 出题助手（demo）

教师向的 AP Computer Science A（Java）出题辅助工具：**RAG 精准检索真题 → DeepSeek 生成 → 规则护栏校验**，覆盖「出题 → 出卷 → 出题篮 → 导出 Word」的完整闭环。

## 功能

| 功能 | 说明 |
|---|---|
| **出题** | 单题生成，或两种出卷模式：单元型（单知识点多题型）、综合型（多知识点自由组合）|
| **精准检索** | 细粒度考点（36 个英文方法/概念，如 get method / method overriding）用 Qdrant filter 硬过滤，embedding 负责排序 |
| **出题篮** | 跨多次生成攒题、审核、移除，localStorage 持久化（刷新不丢）|
| **导出 Word** | 出题篮/出卷一键导出 .docx，题目卷 + 答案卷分页，代码块等宽字体 |
| **上传入库** | 上传 PDF/docx，LLM 提取题目（补全答案/解析/考点/难度）→ 增量入库 |
| **数据治理** | 用户上传的题可删单题、可一键 reset 回官方基线 |
| **内网穿透** | cloudflared 一键公网访问，带 token 鉴权（防止 API key 被刷）|

## 技术栈

- **FastAPI** + **LangGraph**（retrieve → generate → validate 自动重试）
- **langchain-deepseek** 调 `deepseek-v4-flash`（结构化输出，已关思考模式）
- **Qdrant**（本地落盘）+ **fastembed**（dense + BM25）+ **sentence-transformers**（rerank）
- **细粒度知识点 filter 检索**（Qdrant Prefetch.filter）
- **PyMuPDF**（PDF 解析）+ **python-docx**（导出 Word）
- 依赖管理用 **uv**，Python 3.11

## 快速开始

### 本地使用

最简单：**双击 `start.bat`**，脚本会自动同步依赖、启动服务、打开浏览器 `http://localhost:8000`。

手动方式：

```bash
uv sync                                   # 装依赖
uv run uvicorn main:app --reload          # 启动服务
# 浏览器打开 http://localhost:8000
```

首次启动会下载 embedding/rerank 模型（走 HF 镜像，见 `.env`）。

### 内网穿透（让外部用户访问）

**双击 `start.bat`** 即可——它会启动服务 + cloudflared 隧道，并**自动打印公网分享链接**（带 token）。把链接发给别人，对方浏览器打开即用。

```bash
# 手动方式
uv run uvicorn main:app --port 8000                     # 1. 起服务
cloudflared tunnel --url http://localhost:8000           # 2. 起隧道（控制台会显示 URL）
uv run python tunnel_url.py                              # 3. 提取带 token 的分享链接
```

停止：双击 `stop.bat`（停服务 + 停隧道）。

**鉴权**：`.env` 里的 `ACCESS_TOKEN` 非空时，除首页外所有接口都需带 token（header `X-Access-Token` 或 query `?token=`）。分享链接形如 `https://xxx.trycloudflare.com/?token=你的token`，token 会由前端自动存入浏览器。不知道 token 的人无法调用出题接口，避免刷 DeepSeek 额度。

> 注意：cloudflared 免账号 quick tunnel 的 URL 是**临时的、随机的**，每次重启会变。要固定域名需用命名隧道（Cloudflare 账号）或国内工具（natapp 等）。

## 目录结构

```
main.py                  FastAPI 入口（/generate /assemble_paper /export /upload /questions /reset /knowledge_points）
graph.py                 LangGraph 编排（单题 + 出卷 + 选项清洗）
rag.py                   Qdrant 混合检索 + 细粒度考点 filter + 增量索引/删除/重置
llm.py                   DeepSeek（出题/难度标注/考点标注/文档解析四函数）
guardrails.py            规则护栏（5 选项 A-E、字段完整、题型一致）
schemas.py               数据契约（Question / GenerateRequest / PaperRequest / ExportRequest 等）
export.py                导出 Word（题目卷 + 答案卷，代码块/加粗渲染）
pdf_ingest.py            解析 CB 官方题源（PDF/docx）入库
annotate_difficulty.py   大模型批量标注难度
annotate_knowledge_point.py  大模型批量标注细粒度考点
tunnel_url.py            从 cloudflared 日志提取带 token 的分享链接
data/                    syllabus.json + examples.json + questions.json + knowledge_points.json
index.html               教师工作台前端
start.bat / stop.bat     一键启动/停止（服务 + 隧道）
```

## 数据

- **485 道题**（469 选择 + 16 编程），来自 AP Classroom 官方题源（Quiz M1-M10 + ProgressCheck Unit1-10 + Classroom MCQ），覆盖 Unit1-10。
- 每题带细粒度考点（36 个）+ 难度（DeepSeek 标注）+ `source`（official/user 区分官方基线 vs 用户上传）。

## 说明

- **检索架构**：实测 bge-small embedding 分不清 Java 代码细节考点，故考点区分用结构化标签（Qdrant filter 硬过滤），embedding 只做过滤后排序 + 自然语言理解。
- **数据源**：以 `E:\教学材料\AP计算机科学A\CB\CB题` 官方题源为准；`E:\我的课程` 个人材料已取消入库。
- **扫描版真题**（1999-2024）OCR 质量一般，默认未入库，建议商用 API 或人工校对。
- **生产化方向**：MySQL（题目/作答）、Redis（缓存）、Docker 化、评估闭环（RAGAS/LLM 打分）。
