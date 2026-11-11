# D4 基线评测报告

## 口径

- 测试集：20 条分层用例；单次采样，未多次重复取中位数。
- 采集时间：2026-11-11T14:50:53+08:00（Asia/Shanghai）。
- 配置模型：`deepseek-chat`；API 返回模型：`deepseek-flash`
- Provider：`deepseek`；Embedding：`BAAI/bge-m3`。
- 索引：47 个 chunk；跑前已恢复 seed 工单数据。
- 意图准确率：`intent == expected_intent` 条数 / 20。
- 工具调用正确率：工单 6 条中，`tool_trace` 同时匹配工具名和期望关键参数的条数 / 6；不看答案文字。
- 检索命中率：政策 8 条中，有答案样本要求 `expected_policy` 出现在 `citations`；无答案样本以 `citations == []` 为正确，防止制造伪引用。
- 延迟：单条 `handle()` 端到端耗时的 P50 / P95，nearest-rank 算法。
- token：累计全链路所有 LLM 调用的 API usage；输入/输出分别求和，单条均值统一除以 20。
- 转人工率：`fallback == true` 条数 / 20；B2 时业务响应尚无该字段，因此第一版记为 N/A，B3 接入后重跑。

## 五项指标

| 指标 | 结果 | 目标 | 结论 |
| --- | ---: | ---: | --- |
| 意图准确率 | 19/20 = 95.0% | ≥ 80% | 达标 |
| 工具调用正确率 | 5/6 = 83.3% | ≥ 85% | 未达标 |
| 检索命中率 | 7/8 = 87.5% | ≥ 80% | 达标 |
| 延迟 P50 / P95 | 1942.44 / 4333.23 ms | 记录基线 | 已采集 |
| token 输入 / 输出 | 20926 / 2428 （单条均值 1046.30 / 121.40） | 记录基线 | 已采集 |
| 转人工率 | N/A（B3 后统计） | 记录基线 | 待 B3 |

## 分项观察

- 有答案政策检索：6/6。
- 无答案样本未制造引用：1/2。
- 全链路 token 总量：23354，单条均值 1167.70。

### W-5 置信度校准观察

模型自报 confidence 只作观察，不作为正确率替代指标。

| confidence 区间 | 样本数 | 意图正确 | 实际准确率 |
| --- | ---: | ---: | ---: |
| 0.00–0.69 | 1 | 1 | 1/1 = 100.0% |
| 0.70–0.79 | 1 | 1 | 1/1 = 100.0% |
| 0.80–0.89 | 1 | 0 | 0/1 = 0.0% |
| 0.90–1.00 | 17 | 17 | 17/17 = 100.0% |

## 失败样本

| ID | 类别 | 失败原因 | 期望 | 实际 | 工具轨迹 / 引用 |
| --- | --- | --- | --- | --- | --- |
| E08 | policy | retrieval_mismatch | intent=policy_qa, tool=None, policy=None, no_basis=True | intent=policy_qa, confidence=0.96, fallback=None | citations=P002, P002, P002, P002 |
| E13 | ticket | intent_mismatch, tool_mismatch | intent=ticket_op, tool=escalate_ticket, policy=None, no_basis=False | intent=handoff, confidence=0.85, fallback=None | 无 |

## 原始结果

逐条结果、工具参数、引用、LLM 调用明细与 token usage 位于 `evals/results.json`。
