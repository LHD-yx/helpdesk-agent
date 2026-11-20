# HelpDesk Agent

企业内部服务台 Agent：一句话进来，先判断你想干什么，再走对应通道。

- **政策问题** → RAG 检索 → 带引用回答
- **工单问题** → Function Calling → 查 / 建 / 升级工单
- **投诉、超范围、低置信度** → 转人工

FastAPI + Streamlit + SQLite + Chroma，模型走 OpenAI 兼容接口（默认 DeepSeek）。

## 它怎么工作

```
用户提问（带 session_id）
   ↓
会话记忆：取最近 3 轮（可选，无 session_id 则不启用）
   ↓
意图路由（LLM，JSON mode）→ {intent, confidence, standalone_query}
   ├─ policy_qa → 检索 Chroma → 拼上下文 → 生成 → 附引用
   ├─ ticket_op → 工具循环（最多 3 轮）→ SQLite
   └─ handoff   → 转人工
   ↓
兜底判定（低置信度 / 检索无依据 / 工具失败）→ 转人工
```

三条分支都已接真，没有占位答案。完整时序与取舍见 [docs/architecture.md](docs/architecture.md)。

`/chat` 的响应里带 `steps` 字段，记录这次实际做了哪几步（查工单 / 升级工单 / 检索政策 / 转人工），
前端会把它渲染成「执行过程」，而不是只显示一段文字。

## 快速开始

需要 conda（或任意 Python 3.11 环境）与两个可用的 API key。

```powershell
# 1. 环境
conda create -n helpdesk python=3.11 -y
conda activate helpdesk
pip install -r requirements.txt

# 2. 配置：复制模板后填入自己的 key
copy .env.example .env
#   LLM_PROVIDER=deepseek
#   LLM_API_KEY=sk-...
#   LLM_MODEL=deepseek-flash
#   LLM_FALLBACK_PROVIDER=siliconflow
#   LLM_FALLBACK_API_KEY=sk-...      （embedding 会复用这个 key）

# 3. 建库 + 建索引（会调用一次 embedding）
python -m app.db.seed
python scripts\smoke_rag.py

# 4. 起后端（终端 A）
uvicorn app.main:app --port 8000

# 5. 起前端（终端 B）
streamlit run ui\streamlit_app.py
```

前端默认连 `http://127.0.0.1:8000`，可用环境变量 `API_BASE` 覆盖。

> **Windows PowerShell 5.1 提醒**：`@'中文'@ | python -` 会把中文变成问号。
> 需要跑单条用例时用 `python scripts\run_case.py E06`，不要用管道。

## 五分钟验收

### 1. 数据层健康

```powershell
python scripts\check_db.py
```

预期结尾：`结论：数据层健康 ✓`

### 2. 三条分支端到端

```powershell
python scripts\smoke_rag.py
```

预期：`检索命中 2/2`、`端到端命中 4/4`

### 2.1 多步任务

```powershell
python evals\run_multistep.py
```

预期：`多步任务通过 2/2`——验证模型能连续调用两个工具并汇总结果
（例如「T1004 一直没人处理，帮我升级，然后告诉我处理人是谁」）。

### 3. 离线自检（不花钱）

```powershell
python scripts\check_router.py      # 7/7
python scripts\check_tools.py       # 8/8
python scripts\check_retriever.py   # 7/7
python scripts\check_policy.py      # 4/4
python scripts\check_eval.py        # 20 条格式检查
```

### 4. HTTP 接口

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health | ConvertTo-Json
```

预期：

```json
{ "status": "ok", "provider": "deepseek", "model": "deepseek-flash", "db_ready": true }
```

```powershell
python scripts\run_case.py E09
```

预期包含：`intent=ticket_op`、引用为空、答案里出现工单标题与状态。

## 评测结果

20 条分层单轮用例（政策 8 / 工单 6 / 转人工 4 / 边界 2），单次采样；
另有 2 条多步任务用例单独验收（不并入单轮准确率，避免口径混淆）。

| 指标 | 结果 |
| --- | ---: |
| 意图准确率 | 20/20 = 100% |
| 工具调用正确率 | 6/6 = 100% |
| 检索命中率 | 7/8 = 87.5% |
| 延迟 P50 / P95 | 2267 / 5305 ms |
| token 输入 / 输出 | 26206 / 4399（单条均值 1530） |
| 转人工率（fallback） | 2/20 = 10% |

**这组数字来自 2026-11-19 的单次采样。** 同类复跑中检索命中率在 87.5%–100% 之间波动，
说明 20 条样本存在明显的单次采样噪声——引用时应带口径，不要当成稳定上限。

口径、失败样本与逐条明细见 [evals/report.md](evals/report.md)。复跑：

```powershell
python evals\run_eval.py
```

## 已知限制

| 限制 | 说明 |
| --- | --- |
| 记忆为进程内存储 | `session_id` 隔离，最多保留最近 3 轮（6 条消息），30 分钟无活动过期，单条内容截断 200 字符；服务重启或多 worker 部署后历史不共享 |
| 意图准确率的样本量小 | 100% 来自 20 条**自建**用例，存在过拟合风险，不代表线上表现 |
| 评测为单次采样 | 检索命中率在 87.5%–100% 间波动；表中是某一次的结果，不是稳定上限 |
| 政策库只有 4 份 | 报销 / 休假 / 采购 / IT 权限，覆盖范围有限 |
| 无混合检索 | 只有向量检索，专有名词（如工单号）更强的是关键词检索，BM25 列为后续项 |
| 无依据时可能附带相近政策 | 问「育儿假」这类政策库不覆盖的问题时，模型有时会顺带引用年假条款（P002），可能造成误导 |
| 单用户身份写死 | 工单提交人固定 `E005`，真实系统应取自登录态 |
| 无鉴权与限流 | 内网演示定位，未做权限系统 |
| 无容器化 | 未提供 Dockerfile，按本文档本地运行 |
| 延迟偏高 | P95 约 5.3s，主要来自一次请求内的多次 LLM 调用（路由 + 工具循环 + 生成）；未做流式输出 |

## 项目结构

```
app/
  main.py              FastAPI：/health、/chat
  schemas.py           请求 / 响应 / 引用契约
  config.py            配置层（pydantic-settings，启动即校验）
  llm/                 模型抽象、OpenAI 兼容实现、主备降级
  agent/               意图路由、工单工具循环、政策问答、编排
  memory/              会话记忆（进程内、TTL、窗口截断）
  rag/                 切片、embedding、Chroma、检索与引用
  tools/               工单三工具 + JSON Schema 注册表
  db/                  建表、造数
  observability/       结构化 JSON 日志
ui/streamlit_app.py    最小演示前端（必须走 HTTP）
evals/                 20 条评测集、跑分脚本、报告与原始结果
scripts/               各类离线自检与冒烟
data/policies/         4 份政策原文（RAG 原料）
```

## 设计取舍

| 决策 | 选择 | 理由 |
| --- | --- | --- |
| 编排 | 自研显式流程 | 分支与兜底是核心复杂度，自己写的循环才控得住重试与降级 |
| 意图识别 | JSON mode + pydantic 校验 | 分类不是工具调用；非法输出可被明确拒绝 |
| 错误处理 | 错误二分 | 只有超时 / 连不上 / 429 / 5xx 才降级，400/401/403/404 直接暴露 |
| 兜底 | `fallback` 结构化字段 | 降级必须被前端、评测、日志同时感知，不能只写在回答文字里 |
| 前端 | Streamlit 走 HTTP | 演示完整链路，不用后端函数冒充前端 |
| 会话记忆 | 进程内存 + TTL + 3 轮窗口 | 对话含工单细节，落盘要考虑加密与生命周期；两周版用内存，生产换 Redis |
| 执行过程 | `steps` 结构化返回 | 让用户看见「它做了什么」；纯文本答案无法体现多步编排 |

更多决策记录（含被推翻的方案）见 [docs/architecture.md](docs/architecture.md) §4。
