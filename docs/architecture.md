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

## 5. 验收清单（Day14 自查）

- [ ] 输入「报销标准是多少」→ RAG 作答并给出政策来源
- [ ] 输入「查工单 T1001」→ 调用工具返回真实状态
- [ ] 输入「我要投诉，转人工」→ 正确转人工
- [ ] 20 条评测集：意图准确率 ≥ 80%，工具调用正确率 ≥ 85%
- [ ] README 能让陌生人按文档跑起来
- [ ] 能 3 分钟讲清架构、流程、取舍、评测结果
- [ ] 能答：为什么用 RAG？为什么用 Function Calling？工具失败怎么办？怎么评测？
