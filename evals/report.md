# D4 评测报告（修复后定稿）

## 口径

- 测试集：20 条分层用例；单次采样，未多次重复取中位数。
- 采集时间：2026-11-11T15:17:54+08:00（Asia/Shanghai）。
- 配置模型：`deepseek-chat`；API 返回模型：`deepseek-flash`
- Provider：`deepseek`；Embedding：`BAAI/bge-m3`。
- 索引：47 个 chunk；跑前已恢复 seed 工单数据。
- 意图准确率：`intent == expected_intent` 条数 / 20。
- 工具调用正确率：工单 6 条中，`tool_trace` 同时匹配工具名和期望关键参数的条数 / 6；不看答案文字。
- 检索命中率：政策 8 条中，有答案样本要求 `expected_policy` 出现在 `citations`；无答案样本以 `citations == []` 为正确，防止制造伪引用。
- 延迟：单条 `handle()` 端到端耗时的 P50 / P95，nearest-rank 算法。
- token：累计全链路所有 LLM 调用的 API usage；输入/输出分别求和，单条均值统一除以 20。
- 转人工率：结构化降级 `fallback == true` 条数 / 20；按任务卡口径，不把路由直接判成 `handoff` 的情况混入 fallback 数量。

## 五项指标

| 指标 | 结果 | 目标 | 结论 |
| --- | ---: | ---: | --- |
| 意图准确率 | 20/20 = 100.0% | ≥ 80% | 达标 |
| 工具调用正确率 | 6/6 = 100.0% | ≥ 85% | 达标 |
| 检索命中率 | 7/8 = 87.5% | ≥ 80% | 达标 |
| 延迟 P50 / P95 | 2111.77 / 3955.35 ms | 记录基线 | 已采集 |
| token 输入 / 输出 | 24894 / 2571 （单条均值 1244.70 / 128.55） | 记录基线 | 已采集 |
| 转人工率 | 3/20 = 15.0% | 记录基线 | 已统计 |

## 分项观察

- 有答案政策检索：5/6。
- 无答案样本未制造引用：2/2。
- 全链路 token 总量：27465，单条均值 1373.25。

### W-5 置信度校准观察

模型自报 confidence 只作观察，不作为正确率替代指标。

| confidence 区间 | 样本数 | 意图正确 | 实际准确率 |
| --- | ---: | ---: | ---: |
| 0.00–0.69 | 1 | 1 | 1/1 = 100.0% |
| 0.70–0.79 | 1 | 1 | 1/1 = 100.0% |
| 0.80–0.89 | 0 | 0 | N/A |
| 0.90–1.00 | 18 | 18 | 18/18 = 100.0% |

### fallback 原因分布

| fallback_reason | 条数 |
| --- | ---: |
| `no_policy_basis` | 2 |
| `no_policy_hit` | 1 |

## 失败样本

| ID | 类别 | 失败原因 | 期望 | 实际 | 工具轨迹 / 引用 |
| --- | --- | --- | --- | --- | --- |
| E06 | policy | retrieval_mismatch | intent=policy_qa, tool=None, policy=P004, no_basis=False | intent=policy_qa, confidence=0.95, fallback=True | 无 |

## 原始结果

逐条结果、工具参数、引用、LLM 调用明细与 token usage 位于 `evals/results.json`。
