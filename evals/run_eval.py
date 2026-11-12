"""D4 基线评测：逐条运行 handle()，采集并可复现地汇总指标。

用法（项目根目录）：
    python evals\run_eval.py

评测层负责三件业务代码不该承担的事：
1. 跑前恢复 seed 数据，保证工单前提可重复；
2. 包住 LLMService.chat，累计全链路 token；
3. 包住工具循环，保存最终响应里没有暴露的 tool_trace。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent import orchestrator  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import seed  # noqa: E402
from app.llm import get_llm_service  # noqa: E402
from app.rag.vector_store import count as count_rag_chunks  # noqa: E402

DEFAULT_TESTSET = PROJECT_ROOT / "evals" / "testset.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evals" / "results.json"
DEFAULT_REPORT = PROJECT_ROOT / "evals" / "report.md"
TIMEZONE = ZoneInfo("Asia/Shanghai")


def load_testset(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            raise ValueError(f"testset 第 {line_no} 行为空")
        record = json.loads(line)
        if not isinstance(record, dict):
            raise ValueError(f"testset 第 {line_no} 行必须是 JSON 对象")
        records.append(record)
    if len(records) != 20:
        raise ValueError(f"testset 必须是 20 条，当前 {len(records)} 条")
    return records


def reset_database() -> None:
    """恢复工单测试数据；避免升级/新建操作污染下一轮。"""
    conn = seed.connect()
    try:
        seed.create_tables(conn)
        seed.seed(conn)
    finally:
        conn.close()


def percentile_nearest_rank(values: list[float], percentile: int) -> float | None:
    """nearest-rank 百分位：排序后取 ceil(P/100 * N) 名。"""
    if not values or not 0 < percentile <= 100:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def parse_tool_arguments(raw: Any) -> dict[str, Any] | None:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def tool_trace_matches(
    trace: list[dict[str, Any]],
    expected_tool: str | None,
    expected_args: dict[str, Any],
) -> bool:
    """工具名相同且期望的关键参数全部相等，才算调用正确。"""
    if expected_tool is None:
        return False
    for call in trace:
        if call.get("name") != expected_tool:
            continue
        actual_args = parse_tool_arguments(call.get("arguments"))
        if actual_args is None:
            continue
        if all(actual_args.get(key) == value for key, value in expected_args.items()):
            return True
    return False


def retrieval_matches(record: dict[str, Any], citations: list[dict[str, Any]]) -> bool:
    """政策答案要求命中期望政策；无答案样本要求不制造引用。"""
    citation_ids = {citation["policy_id"] for citation in citations}
    if record["expect_no_basis"]:
        return not citation_ids
    expected_policy = record["expected_policy"]
    return expected_policy is not None and expected_policy in citation_ids


def summarize_results(records: list[dict[str, Any]]) -> dict[str, Any]:
    intent_denominator = len(records)
    intent_correct = sum(record["checks"]["intent_ok"] for record in records)

    ticket_records = [record for record in records if record["category"] == "ticket"]
    tool_correct = sum(
        record["checks"]["tool_ok"] is True for record in ticket_records
    )

    policy_records = [record for record in records if record["category"] == "policy"]
    retrieval_correct = sum(
        record["checks"]["retrieval_ok"] is True for record in policy_records
    )

    latencies = [
        record["latency_ms"] for record in records if record["latency_ms"] is not None
    ]
    prompt_tokens = sum(record["token_usage"]["prompt_tokens"] for record in records)
    completion_tokens = sum(
        record["token_usage"]["completion_tokens"] for record in records
    )

    fallback_states = [record.get("fallback") for record in records]
    fallback_available = all(isinstance(state, bool) for state in fallback_states)
    fallback_count = (
        sum(state is True for state in fallback_states) if fallback_available else None
    )

    return {
        "intent": {
            "correct": intent_correct,
            "total": intent_denominator,
            "rate": intent_correct / intent_denominator if intent_denominator else None,
        },
        "tool": {
            "correct": tool_correct,
            "total": len(ticket_records),
            "rate": tool_correct / len(ticket_records) if ticket_records else None,
        },
        "retrieval": {
            "correct": retrieval_correct,
            "total": len(policy_records),
            "rate": retrieval_correct / len(policy_records) if policy_records else None,
            "answerable_correct": sum(
                record["checks"]["retrieval_ok"] is True
                for record in policy_records
                if not record["expect_no_basis"]
            ),
            "answerable_total": sum(
                not record["expect_no_basis"] for record in policy_records
            ),
            "no_basis_correct": sum(
                record["checks"]["retrieval_ok"] is True
                for record in policy_records
                if record["expect_no_basis"]
            ),
            "no_basis_total": sum(
                record["expect_no_basis"] for record in policy_records
            ),
        },
        "latency_ms": {
            "p50": percentile_nearest_rank(latencies, 50),
            "p95": percentile_nearest_rank(latencies, 95),
            "method": "nearest-rank",
        },
        "tokens": {
            "prompt_total": prompt_tokens,
            "completion_total": completion_tokens,
            "total": prompt_tokens + completion_tokens,
            "prompt_mean": prompt_tokens / intent_denominator if intent_denominator else None,
            "completion_mean": (
                completion_tokens / intent_denominator if intent_denominator else None
            ),
            "total_mean": (
                (prompt_tokens + completion_tokens) / intent_denominator
                if intent_denominator
                else None
            ),
            "source": "API usage，累计全部路由/政策/工具循环 LLM 调用",
        },
        "fallback": {
            "available": fallback_available,
            "count": fallback_count,
            "rate": (
                fallback_count / intent_denominator
                if fallback_available and intent_denominator
                else None
            ),
        },
    }


def _calibration(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets = [
        ("0.00–0.69", 0.0, 0.7),
        ("0.70–0.79", 0.7, 0.8),
        ("0.80–0.89", 0.8, 0.9),
        ("0.90–1.00", 0.9, 1.000001),
    ]
    output: list[dict[str, Any]] = []
    for label, low, high in buckets:
        selected = [
            record
            for record in records
            if record["confidence"] is not None
            and low <= record["confidence"] < high
        ]
        correct = sum(record["checks"]["intent_ok"] for record in selected)
        output.append(
            {
                "range": label,
                "count": len(selected),
                "correct": correct,
                "rate": correct / len(selected) if selected else None,
            }
        )
    return output


def _failure_reasons(record: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if record["error"]:
        reasons.append("evaluation_error")
    if not record["checks"]["intent_ok"]:
        reasons.append("intent_mismatch")
    if record["checks"]["tool_ok"] is False:
        reasons.append("tool_mismatch")
    if record["checks"]["retrieval_ok"] is False:
        # 只写 retrieval_mismatch 会让人以为"检索没命中"，
        # 实际也可能是召回了但模型拒答。带上 fallback_reason 才能区分。
        detail = record.get("fallback_reason") or "no_citation"
        reasons.append(f"retrieval_mismatch({detail})")
    return reasons


def _clean_error(exc: Exception) -> dict[str, str]:
    return {"type": type(exc).__name__, "message": str(exc)}


def run_case(
    record: dict[str, Any],
    current_calls: dict[str, Any],
    current_trace: dict[str, Any],
) -> dict[str, Any]:
    current_calls["items"] = []
    current_trace["items"] = []
    response = None
    error = None
    started = time.perf_counter()
    try:
        response = orchestrator.handle(
            record["message"], session_id=f"eval-{record['id']}"
        )
    except Exception as exc:  # 评测层记录单条失败后继续跑完，避免一次故障丢掉整批。
        error = _clean_error(exc)
    latency_ms = (time.perf_counter() - started) * 1000

    calls = current_calls["items"]
    trace = current_trace["items"]
    citations = (
        [citation.model_dump(mode="json") for citation in response.citations]
        if response is not None
        else []
    )
    intent = response.intent.value if response is not None else None
    confidence = response.confidence if response is not None else None
    fallback = getattr(response, "fallback", None) if response is not None else None
    fallback_reason = (
        getattr(response, "fallback_reason", None) if response is not None else None
    )

    intent_ok = intent == record["expected_intent"]
    tool_ok = (
        tool_trace_matches(
            trace, record["expected_tool"], record["expected_tool_args"]
        )
        if record["category"] == "ticket"
        else None
    )
    retrieval_ok = (
        retrieval_matches(record, citations)
        if record["category"] == "policy"
        else None
    )

    prompt_tokens = sum(call["prompt_tokens"] for call in calls)
    completion_tokens = sum(call["completion_tokens"] for call in calls)
    return {
        "id": record["id"],
        "category": record["category"],
        "message": record["message"],
        "expect_no_basis": record["expect_no_basis"],
        "expected": {
            "intent": record["expected_intent"],
            "tool": record["expected_tool"],
            "tool_args": record["expected_tool_args"],
            "policy": record["expected_policy"],
            "no_basis": record["expect_no_basis"],
        },
        "intent": intent,
        "confidence": confidence,
        "answer": response.answer if response is not None else "",
        "citations": citations,
        "tool_trace": trace,
        "latency_ms": latency_ms,
        "token_usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "llm_calls": len(calls),
        },
        "llm_calls": calls,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "checks": {
            "intent_ok": intent_ok,
            "tool_ok": tool_ok,
            "retrieval_ok": retrieval_ok,
        },
        "error": error,
    }


def run_all(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_calls: dict[str, Any] = {"items": []}
    current_trace: dict[str, Any] = {"items": []}
    service = get_llm_service()
    original_chat = service.chat
    original_tool_loop = orchestrator.run_tool_loop

    def tracked_chat(messages: list[dict[str, Any]], **kwargs: Any):
        result = original_chat(messages, **kwargs)
        current_calls["items"].append(
            {
                "model": result.model,
                "served_by": result.served_by,
                "degraded": result.degraded,
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "latency_ms": result.latency_ms,
            }
        )
        return result

    def tracked_tool_loop(message: str, *args: Any, **kwargs: Any):
        result = original_tool_loop(message, *args, **kwargs)
        current_trace["items"] = result.get("tool_calls", [])
        return result

    service.chat = tracked_chat
    orchestrator.run_tool_loop = tracked_tool_loop
    results: list[dict[str, Any]] = []
    try:
        for index, record in enumerate(records, 1):
            result = run_case(record, current_calls, current_trace)
            results.append(result)
            status = (
                "OK"
                if result["checks"]["intent_ok"]
                and result["checks"]["tool_ok"] is not False
                and result["checks"]["retrieval_ok"] is not False
                and result["error"] is None
                else "FAIL"
            )
            print(
                f"[{status}] {index:02d}/20 {record['id']} "
                f"{result['latency_ms']:.0f}ms "
                f"{result['token_usage']['total_tokens']}tok "
                f"intent={result['intent']}"
            )
            if result["error"]:
                print(f"       error={result['error']['type']}: {result['error']['message']}")
    finally:
        service.chat = original_chat
        orchestrator.run_tool_loop = original_tool_loop
    return results


def _fmt_rate(numerator: int | None, denominator: int | None) -> str:
    if numerator is None or not denominator:
        return "N/A"
    return f"{numerator}/{denominator} = {numerator / denominator:.1%}"


def _fmt_number(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def build_report(
    results: list[dict[str, Any]],
    summary: dict[str, Any],
    metadata: dict[str, Any],
) -> str:
    failures = [record for record in results if _failure_reasons(record)]
    models = sorted(
        {
            call["model"]
            for record in results
            for call in record["llm_calls"]
            if call["model"]
        }
    )
    calibration = _calibration(results)

    lines = [
        "# D4 评测报告（修复后定稿）",
        "",
        "## 口径",
        "",
        f"- 测试集：{len(results)} 条分层用例；单次采样，未多次重复取中位数。",
        f"- 采集时间：{metadata['sampled_at']}（Asia/Shanghai）。",
        f"- 配置模型：`{metadata['configured_model']}`；API 返回模型："
        + (", ".join(f"`{model}`" for model in models) if models else "无成功调用"),
        f"- Provider：`{metadata['provider']}`；Embedding：`{metadata['embedding_model']}`。",
        f"- 索引：{metadata['rag_chunks']} 个 chunk；跑前已恢复 seed 工单数据。",
        "- 意图准确率：`intent == expected_intent` 条数 / 20。",
        "- 工具调用正确率：工单 6 条中，`tool_trace` 同时匹配工具名和期望关键参数的条数 / 6；"
        "不看答案文字。",
        "- 检索命中率：政策 8 条中，有答案样本要求 `expected_policy` 出现在 `citations`；"
        "无答案样本以 `citations == []` 为正确，防止制造伪引用。",
        "- 延迟：单条 `handle()` 端到端耗时的 P50 / P95，nearest-rank 算法。",
        "- token：累计全链路所有 LLM 调用的 API usage；输入/输出分别求和，"
        "单条均值统一除以 20。",
        "- 转人工率：结构化降级 `fallback == true` 条数 / 20；按任务卡口径，"
        "不把路由直接判成 `handoff` 的情况混入 fallback 数量。",
        "",
        "## 五项指标",
        "",
        "| 指标 | 结果 | 目标 | 结论 |",
        "| --- | ---: | ---: | --- |",
        (
            f"| 意图准确率 | "
            f"{_fmt_rate(summary['intent']['correct'], summary['intent']['total'])} "
            f"| ≥ 80% | {'达标' if summary['intent']['rate'] >= 0.8 else '未达标'} |"
        ),
        (
            f"| 工具调用正确率 | "
            f"{_fmt_rate(summary['tool']['correct'], summary['tool']['total'])} "
            f"| ≥ 85% | {'达标' if summary['tool']['rate'] >= 0.85 else '未达标'} |"
        ),
        (
            f"| 检索命中率 | "
            f"{_fmt_rate(summary['retrieval']['correct'], summary['retrieval']['total'])} "
            f"| ≥ 80% | {'达标' if summary['retrieval']['rate'] >= 0.8 else '未达标'} |"
        ),
        (
            f"| 延迟 P50 / P95 | "
            f"{_fmt_number(summary['latency_ms']['p50'])} / "
            f"{_fmt_number(summary['latency_ms']['p95'])} ms "
            "| 记录基线 | 已采集 |"
        ),
        (
            f"| token 输入 / 输出 | "
            f"{summary['tokens']['prompt_total']} / "
            f"{summary['tokens']['completion_total']} "
            f"（单条均值 {_fmt_number(summary['tokens']['prompt_mean'])} / "
            f"{_fmt_number(summary['tokens']['completion_mean'])}） "
            "| 记录基线 | 已采集 |"
        ),
        (
            "| 转人工率 | "
            + (
                _fmt_rate(summary["fallback"]["count"], len(results))
                if summary["fallback"]["available"]
                else "N/A（B3 后统计）"
            )
            + " | 记录基线 | 已统计 |"
        ),
        "",
        "## 分项观察",
        "",
        (
            f"- 有答案政策检索："
            f"{summary['retrieval']['answerable_correct']}/"
            f"{summary['retrieval']['answerable_total']}。"
        ),
        (
            f"- 无答案样本未制造引用："
            f"{summary['retrieval']['no_basis_correct']}/"
            f"{summary['retrieval']['no_basis_total']}。"
        ),
        f"- 全链路 token 总量：{summary['tokens']['total']}，"
        f"单条均值 {_fmt_number(summary['tokens']['total_mean'])}。",
        "",
        "### W-5 置信度校准观察",
        "",
        "模型自报 confidence 只作观察，不作为正确率替代指标。",
        "",
        "| confidence 区间 | 样本数 | 意图正确 | 实际准确率 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for bucket in calibration:
        lines.append(
            f"| {bucket['range']} | {bucket['count']} | {bucket['correct']} | "
            f"{_fmt_rate(bucket['correct'], bucket['count'])} |"
        )

    fallback_reasons = Counter(
        record["fallback_reason"]
        for record in results
        if record["fallback"] is True
    )
    lines.extend(
        [
            "",
            "### fallback 原因分布",
            "",
            "| fallback_reason | 条数 |",
            "| --- | ---: |",
        ]
    )
    if fallback_reasons:
        for reason, count in sorted(fallback_reasons.items()):
            lines.append(f"| `{reason}` | {count} |")
    else:
        lines.append("| 无 | 0 |")

    lines.extend(["", "## 失败样本", ""])
    if not failures:
        lines.append("本版无失败样本。")
    else:
        lines.extend(
            [
                "| ID | 类别 | 失败原因 | 期望 | 实际 | 工具轨迹 / 引用 |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for record in failures:
            evidence = []
            if record["tool_trace"]:
                evidence.append(
                    "tools="
                    + ", ".join(call.get("name", "?") for call in record["tool_trace"])
                )
            if record["citations"]:
                evidence.append(
                    "citations="
                    + ", ".join(
                        citation["policy_id"] for citation in record["citations"]
                    )
                )
            if record["error"]:
                evidence.append(
                    f"error={record['error']['type']}: {record['error']['message']}"
                )
            expected = (
                f"intent={record['expected']['intent']}, "
                f"tool={record['expected']['tool']}, "
                f"policy={record['expected']['policy']}, "
                f"no_basis={record['expected']['no_basis']}"
            )
            actual = (
                f"intent={record['intent']}, confidence={record['confidence']}, "
                f"fallback={record['fallback']}"
            )
            lines.append(
                f"| {record['id']} | {record['category']} | "
                f"{', '.join(_failure_reasons(record))} | {expected} | {actual} | "
                f"{'; '.join(evidence) or '无'} |"
            )

    lines.extend(
        [
            "",
            "## 原始结果",
            "",
            "逐条结果、工具参数、引用、LLM 调用明细与 token usage 位于 `evals/results.json`。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 HelpDesk Agent D4 评测")
    parser.add_argument("--testset", type=Path, default=DEFAULT_TESTSET)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()

    sys.stdout.reconfigure(encoding="utf-8")
    print("检查评测集 ...")
    records = load_testset(args.testset)
    print(f"已载入 {len(records)} 条；恢复 seed 数据 ...")
    reset_database()

    rag_chunks = count_rag_chunks()
    if rag_chunks <= 0:
        print("[FAIL] Chroma 索引为空，先运行 python -m app.rag.indexer")
        return 1

    config = get_settings()
    metadata = {
        "sampled_at": datetime.now(TIMEZONE).isoformat(timespec="seconds"),
        "timezone": "Asia/Shanghai",
        "testset": str(args.testset.relative_to(PROJECT_ROOT)),
        "testset_size": len(records),
        "sample_rounds": 1,
        "configured_model": config.resolved_model,
        "provider": config.llm_provider,
        "embedding_model": config.embedding_model,
        "rag_chunks": rag_chunks,
        "database_reset": True,
    }

    print(
        f"配置模型 {metadata['configured_model']}；开始 20 条端到端评测 ..."
    )
    results = run_all(records)
    summary = summarize_results(results)
    payload = {"metadata": metadata, "summary": summary, "results": results}
    args.results.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.report.write_text(
        build_report(results, summary, metadata), encoding="utf-8"
    )

    print("")
    print(
        "意图准确率："
        f"{_fmt_rate(summary['intent']['correct'], summary['intent']['total'])}"
    )
    print(
        "工具调用正确率："
        f"{_fmt_rate(summary['tool']['correct'], summary['tool']['total'])}"
    )
    print(
        "检索命中率："
        f"{_fmt_rate(summary['retrieval']['correct'], summary['retrieval']['total'])}"
    )
    print(
        "P50 / P95："
        f"{_fmt_number(summary['latency_ms']['p50'])} / "
        f"{_fmt_number(summary['latency_ms']['p95'])} ms"
    )
    print(
        "token 输入 / 输出："
        f"{summary['tokens']['prompt_total']} / "
        f"{summary['tokens']['completion_total']}"
    )
    print(f"结果：{args.results}")
    print(f"报告：{args.report}")

    targets_ok = (
        summary["intent"]["rate"] >= 0.8 and summary["tool"]["rate"] >= 0.85
    )
    all_ran = len(results) == len(records)
    return 0 if targets_ok and all_ran else 1


if __name__ == "__main__":
    raise SystemExit(main())
