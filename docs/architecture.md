# HelpDesk Agent 架构说明

> 这份文档同时是 Day1 的产出和最终 README 的素材。面试前你要能只看这张图讲 3 分钟。

## 1. 问题定义

企业内部服务台每天要接两类问题：

- **政策类**（可查文档回答）：报销标准、年假规则、OA 流程怎么走
- **工单类**（要操作数据）：查工单进度、建工单、升级工单

痛点有两个：政策文档散落在各处，人工翻找慢且答复口径不一致；工单系统要用专门界面操作，普通员工不会用。

所以这个 Agent 要做的不是「陪聊」，而是**在一条对话链路里判断用户到底想干什么，然后走对应的正确通道**；判断不了就转人工，绝不硬答。

## 2. 运行时序

```
用户提问 "查工单 T1001"
      |
      v
 [1] 载入会话历史  SessionStore.get(sid)            ~0ms
     └─ 超过 N 轮 → 触发摘要压缩
      |
      v
 [2] 意图路由  Intent Router                        ~0.5-1.5s
     LLM 结构化输出 → {intent, confidence, slots, reason}
      |
      +-----------+-----------+-----------+
      v           v           v
  policy_qa   ticket_op    handoff
      |           |           |
      |           |           └─ 直接返回转人工卡片
      |           |
      |           └─ [3b] 工具循环（最多 3 轮）
      |                LLM → tool_calls → 执行 SQLite
      |                → 结果回灌 → LLM → 答案 / 再调工具
      |
      └─ [3a] RAG
           检索（Chroma 向量 + BM25 关键词 双路）
           → 合并去重 → 拼 prompt
           → LLM 生成（强制基于检索内容）
           → 附 citations[doc_id, 章节, 原文片段]
      |
      v
 [3] 兜底判定
     置信度 < 阈值 / 工具失败 / 超时 / 越权
          → 降级：转人工 + 说明原因
      |
      v
 [4] 写回记忆（滚动窗口 / 摘要替换）
 [5] 返回 {answer, citations, intent, tool_trace, latency_ms, usage}
```

## 3. 分层

```
 [ 前端 ]  Streamlit 演示界面  /  curl 调试
      |  HTTP JSON
 [ 服务层 ]  FastAPI
      POST /chat        GET /health        GET /sessions/{id}
      中间件：请求 ID 注入 · 耗时与 token 记录 · 全局异常兜底
      |
 [ 编排层 ]  orchestrator
      记忆 → 路由 → 分支 → 兜底 → 落库
      |
      +----------------+----------------+
      v                v                v
 [ LLM 抽象层 ]   [ 知识层 ]        [ 工具层 ]
  DeepSeek        Chroma 向量库      SQLite
  硅基流动         + BM25 关键词      tickets / employees / policies
  Ollama          BGE embedding
                  政策文档
      |
 [ 横切 ]  config · logging · metrics · evals
```

## 4. 选型决策记录（ADR）

| 决策点 | 选择 | 放弃的方案 | 理由 |
| --- | --- | --- | --- |
| 编排 | 自研显式流程 | LangChain AgentExecutor / LangGraph / LlamaIndex | 核心复杂度在分支与兜底，不在链抽象。自己写的循环每一行都讲得出，也才控得住重试与降级 |
| 向量库 | Chroma | FAISS / pgvector / Milvus | 需要 metadata 过滤 + 零部署；FAISS 无 metadata 管理，服务型向量库要额外部署 |
| Embedding | 待定（硅基流动 `BAAI/bge-m3` API 或本地 BGE-small-zh） | Chroma 默认 all-MiniLM / 本地 bge-m3 | 默认模型是英文模型，中文不可用；本地 bge-m3 体积大、CPU 慢 |
| 主 LLM | DeepSeek-chat | Ollama 本地 7B | 本机无 NVIDIA 显卡，7B 在 CPU 上慢且 function calling 不稳定，会把不确定性引进核心链路 |
| 记忆 | 自研 SessionStore | LangChain Memory / Redis | 抽象够薄、便于讲清实现；Redis 需要额外部署 |
| 前端 | Streamlit | Gradio / 手写 HTML | 单文件、能展示中间步骤与引用来源；不值得为演示花时间写 HTML |
| 错误处理 | 错误二分：只有"服务不可用"才降级 | 统一 except Exception 后降级 | 400/401/403/404 属于"我的问题"，换供应商也一样失败；一律降级会让配错被一次"成功"的降级掩盖（模型名写错 → 静默降级 → 返回完全正常的答案，故障零暴露） |

## 5. 验收清单（Day14 自查）

- [ ] 输入「报销标准是多少」→ RAG 作答并给出政策来源
- [ ] 输入「查工单 T1001」→ 调用工具返回真实状态
- [ ] 输入「我要投诉，转人工」→ 正确转人工
- [ ] 20 条评测集：意图准确率 ≥ 80%，工具调用正确率 ≥ 85%
- [ ] README 能让陌生人按文档跑起来
- [ ] 能 3 分钟讲清架构、流程、取舍、评测结果
- [ ] 能答：为什么用 RAG？为什么用 Function Calling？工具失败怎么办？怎么评测？

## 6. 实现现状（2026-11-12）

| 模块 | 文件 | 状态 | 说明 |
| --- | --- | --- | --- |
| 配置层 | `app/config.py` | ✅ | 启动即校验供应商与模型；key 只从环境读取 |
| 模型抽象 | `app/llm/` | ✅ | OpenAI 兼容实现；主备降级；`max_tokens` 透传 |
| 数据层 | `app/db/` | ✅ | 三张表、外键、CHECK、幂等建库 |
| 意图路由 | `app/agent/router.py` | ✅ | JSON mode；非法 JSON / 非法枚举 / 低置信度统一转人工 |
| 工单工具 | `app/tools/` | ✅ | 查 / 建 / 升级；结构化错误；白名单分发 |
| 工具循环 | `app/agent/ticket_ops.py` | ✅ | 最多 3 轮；回灌 `role=tool`；轮数上限兜底 |
| 知识层 | `app/rag/` | ✅ | 按标题切片 47 块；bge-m3 1024 维；阈值 0.55；复合问句拆分 |
| 政策问答 | `app/agent/policy_qa.py` | ✅ | 引用由代码拼；全拒 / 部分拒分级 |
| 编排 | `app/agent/orchestrator.py` | ✅ | 三路分派；request_id；降级与 token 汇总 |
| 可观测 | `app/observability/` | ✅ | JSON 行日志；`chat_start` / `chat_done` |
| 前端 | `ui/streamlit_app.py` | ✅ | 走 HTTP；引用卡片；状态标记；已知限制 |
| 评测 | `evals/` | ✅ | 20 条分层用例；六项指标；报告与原始结果 |

实际调用链：

```
Streamlit → POST /chat → orchestrator.handle()
  → router.classify()            （1 次 LLM）
  ├─ policy_qa → retriever（拆分 + 向量）→ policy_qa.answer()（1 次 LLM）
  ├─ ticket_op → run_tool_loop()（1–3 次 LLM + 工具执行）
  └─ handoff   → 直接返回
  → 写 chat_done 日志 → ChatResponse
```

## 7. 与原设计的差异

| 原计划 | 实际 | 原因 |
| --- | --- | --- |
| BM25 + 向量混合检索 | 只做向量 | 时间不足；已列入投递后补课项 |
| 多轮记忆 + 上下文压缩 | 未实现，`session_id` 仅透传 | 与 D4 评测合并后时间不够；UI 已如实标注 |
| 权限系统 | 提交人固定 `E005` | 两周版范围外 |
| Docker / CI | 未做 | 保留在投递后补课清单 |
| 高级重排 | 未做 | 同上 |

**这些差异不回填进"已完成"清单**，而是以"已知限制"的形式同时出现在 README 与本文档中——面试被追问时，答"我知道缺什么、为什么缺、下一步怎么做"，比假装做全了更可信。
