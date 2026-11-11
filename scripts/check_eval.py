"""离线检查 D4 评测集，不调用 LLM、检索或工单工具。

检查四件事：
1. JSONL 行数、字段、ID、消息都合法；
2. 政策 / 工单 / 转人工 / 边界四层数量符合设计；
3. 期望值与意图、政策 ID、工具参数的关系一致；
4. 工单用例的初始数据前提仍与 seed.py 一致。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.db.seed import TICKETS  # noqa: E402

TESTSET_PATH = PROJECT_ROOT / "evals" / "testset.jsonl"

REQUIRED_FIELDS = {
    "id",
    "category",
    "message",
    "expected_intent",
    "expected_tool",
    "expected_tool_args",
    "expected_policy",
    "expect_no_basis",
    "precondition",
    "note",
}
CATEGORY_COUNTS = {
    "policy": 8,
    "ticket": 6,
    "handoff": 4,
    "boundary": 2,
}
CATEGORY_INTENTS = {
    "policy": {"policy_qa"},
    "ticket": {"ticket_op"},
    "handoff": {"handoff"},
    "boundary": {"ticket_op", "handoff"},
}
POLICY_IDS = {"P001", "P002", "P003", "P004"}
TOOL_ARG_KEYS = {
    "get_ticket": {"ticket_id"},
    "create_ticket": {"category", "priority"},
    "escalate_ticket": {"ticket_id"},
}
PRECONDITION_FIELDS = {"ticket_id", "exists", "status", "escalated"}
TICKET_BY_ID = {row[0]: row for row in TICKETS}


def _load_records(path: Path) -> tuple[list[dict[str, Any]], list[str]]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"无法读取 {path}: {exc}"]

    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            errors.append(f"第 {line_no} 行为空；JSONL 不允许空行")
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"第 {line_no} 行不是合法 JSON：{exc.msg}")
            continue
        if not isinstance(record, dict):
            errors.append(f"第 {line_no} 行必须是 JSON 对象")
            continue
        record["_line_no"] = line_no
        records.append(record)

    return records, errors


def _check_record(record: dict[str, Any]) -> list[str]:
    line_no = record["_line_no"]
    prefix = f"第 {line_no} 行"
    errors: list[str] = []

    actual_fields = set(record) - {"_line_no"}
    missing = REQUIRED_FIELDS - actual_fields
    extra = actual_fields - REQUIRED_FIELDS
    if missing:
        errors.append(f"{prefix} 缺字段：{sorted(missing)}")
    if extra:
        errors.append(f"{prefix} 有未知字段：{sorted(extra)}")
    if missing:
        return errors

    category = record["category"]
    intent = record["expected_intent"]
    tool = record["expected_tool"]
    tool_args = record["expected_tool_args"]
    policy = record["expected_policy"]
    no_basis = record["expect_no_basis"]
    message = record["message"]
    note = record["note"]

    if category not in CATEGORY_COUNTS:
        errors.append(f"{prefix} category 非法：{category!r}")
    elif intent not in CATEGORY_INTENTS[category]:
        errors.append(
            f"{prefix} {category} 的 expected_intent 不能是 {intent!r}"
        )

    if not isinstance(message, str) or not message.strip():
        errors.append(f"{prefix} message 不能为空")
    elif len(message) > 2000:
        errors.append(f"{prefix} message 超过 2000 字")

    if not isinstance(note, str) or not note.strip():
        errors.append(f"{prefix} note 不能为空")
    elif len(note) > 300:
        errors.append(f"{prefix} note 超过 300 字")

    if not isinstance(tool_args, dict):
        errors.append(f"{prefix} expected_tool_args 必须是对象")
    elif category == "ticket":
        if tool not in TOOL_ARG_KEYS:
            errors.append(f"{prefix} 未知工具：{tool!r}")
        else:
            allowed_keys = TOOL_ARG_KEYS[tool]
            unknown_keys = set(tool_args) - allowed_keys
            if not tool_args:
                errors.append(f"{prefix} 工单用例必须标注关键工具参数")
            if unknown_keys:
                errors.append(
                    f"{prefix} {tool} 不允许机判这些参数：{sorted(unknown_keys)}"
                )
            if tool in {"get_ticket", "escalate_ticket"} and not tool_args.get(
                "ticket_id"
            ):
                errors.append(f"{prefix} {tool} 必须标注 ticket_id")
            if tool == "create_ticket" and not tool_args.get("category"):
                errors.append(f"{prefix} create_ticket 必须标注 category")
    elif tool is not None or tool_args:
        errors.append(f"{prefix} 非工单层 expected_tool 应为 null、参数应为空")

    if category == "policy":
        if no_basis:
            if policy is not None:
                errors.append(f"{prefix} 无答案政策用例的 expected_policy 必须为 null")
        elif policy not in POLICY_IDS:
            errors.append(f"{prefix} 政策用例必须使用 P001–P004，当前为 {policy!r}")
    elif policy is not None or no_basis:
        errors.append(f"{prefix} 非政策层 expected_policy 应为 null、expect_no_basis 应为 false")

    errors.extend(_check_precondition(record))
    return errors


def _check_precondition(record: dict[str, Any]) -> list[str]:
    prefix = f"第 {record['_line_no']} 行"
    precondition = record["precondition"]

    if precondition is None:
        if record["expected_tool"] in {"get_ticket", "escalate_ticket"}:
            return [f"{prefix} 查/升级工单用例必须声明初始数据前提"]
        return []
    if not isinstance(precondition, dict) or set(precondition) != PRECONDITION_FIELDS:
        return [f"{prefix} precondition 字段必须恰为 {sorted(PRECONDITION_FIELDS)}"]

    ticket_id = precondition["ticket_id"]
    row = TICKET_BY_ID.get(ticket_id)
    exists = row is not None
    expected_ticket_id = record["expected_tool_args"].get("ticket_id")
    if expected_ticket_id is not None and ticket_id != expected_ticket_id:
        return [f"{prefix} precondition.ticket_id 与 expected_tool_args 不一致"]

    if precondition["exists"] is not exists:
        return [f"{prefix} {ticket_id} 的 exists 前提与 seed.py 不一致"]
    if not exists:
        if precondition["status"] is not None or precondition["escalated"] is not None:
            return [f"{prefix} 不存在工单的 status / escalated 必须为 null"]
        return []

    actual_status = row[3]
    actual_escalated = row[10] is not None
    if precondition["status"] != actual_status:
        return [
            f"{prefix} {ticket_id} 初始 status 应为 {actual_status!r}，"
            f"评测集写的是 {precondition['status']!r}"
        ]
    if precondition["escalated"] is not actual_escalated:
        return [
            f"{prefix} {ticket_id} 初始 escalated 应为 {actual_escalated}，"
            f"评测集写的是 {precondition['escalated']!r}"
        ]
    return []


def _check_collection(records: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [record.get("id") for record in records]
    counts = Counter(record.get("category") for record in records)
    messages = [record.get("message") for record in records]

    if len(records) != 20:
        errors.append(f"评测集必须恰好 20 条，当前 {len(records)} 条")
    if len(set(ids)) != len(ids):
        errors.append("评测集存在重复 id")
    if ids != [f"E{i:02d}" for i in range(1, 21)]:
        errors.append("id 必须按 E01–E20 的顺序连续排列")
    if len(set(messages)) != len(messages):
        errors.append("评测集存在重复 message")
    if dict(counts) != CATEGORY_COUNTS:
        errors.append(
            f"四层数量必须为 {CATEGORY_COUNTS}，当前 {dict(counts)}"
        )

    policy_records = [r for r in records if r.get("category") == "policy"]
    no_basis_count = sum(r.get("expect_no_basis") is True for r in policy_records)
    if no_basis_count != 2:
        errors.append(f"政策层必须包含 2 条无答案，当前 {no_basis_count} 条")

    covered_policies = {
        r.get("expected_policy")
        for r in policy_records
        if r.get("expected_policy") is not None
    }
    if covered_policies != POLICY_IDS:
        errors.append(
            f"政策覆盖必须包含 {sorted(POLICY_IDS)}，当前 {sorted(covered_policies)}"
        )

    ticket_records = [r for r in records if r.get("category") == "ticket"]
    covered_tools = {r.get("expected_tool") for r in ticket_records}
    if covered_tools != set(TOOL_ARG_KEYS):
        errors.append(
            f"工单层必须覆盖 {sorted(TOOL_ARG_KEYS)}，当前 {sorted(covered_tools)}"
        )

    boundary_messages = [
        r.get("message", "") for r in records if r.get("category") == "boundary"
    ]
    if not any(len(message) <= 10 for message in boundary_messages):
        errors.append("边界层缺少不超过 10 字的极短输入")
    if not any(len(message) > 200 for message in boundary_messages):
        errors.append("边界层缺少超过 200 字的长描述")

    return errors


def _check_metric_algorithms() -> list[str]:
    """用固定合成数据验证指标定义，不访问网络或业务数据库。"""
    from evals.run_eval import (  # 延迟导入，避免检查脚本启动时初始化业务单例。
        percentile_nearest_rank,
        retrieval_matches,
        summarize_results,
        tool_trace_matches,
    )

    errors: list[str] = []
    fake_results = [
        {
            "category": "policy",
            "expect_no_basis": False,
            "checks": {"intent_ok": True, "tool_ok": None, "retrieval_ok": True},
            "latency_ms": 10.0,
            "token_usage": {"prompt_tokens": 3, "completion_tokens": 1},
            "fallback": True,
        },
        {
            "category": "ticket",
            "expect_no_basis": False,
            "checks": {"intent_ok": True, "tool_ok": False, "retrieval_ok": None},
            "latency_ms": 20.0,
            "token_usage": {"prompt_tokens": 2, "completion_tokens": 2},
            "fallback": False,
        },
        {
            "category": "handoff",
            "expect_no_basis": False,
            "checks": {"intent_ok": False, "tool_ok": None, "retrieval_ok": None},
            "latency_ms": 30.0,
            "token_usage": {"prompt_tokens": 5, "completion_tokens": 1},
            "fallback": False,
        },
    ]
    summary = summarize_results(fake_results)

    checks = [
        (summary["intent"]["correct"] == 2 and summary["intent"]["total"] == 3,
         "意图准确率分母或命中数错误"),
        (summary["tool"]["correct"] == 0 and summary["tool"]["total"] == 1,
         "工具正确率分母或命中数错误"),
        (summary["retrieval"]["correct"] == 1
         and summary["retrieval"]["total"] == 1,
         "检索命中率分母或命中数错误"),
        (percentile_nearest_rank([30.0, 10.0, 20.0], 50) == 20.0,
         "P50 nearest-rank 算法错误"),
        (percentile_nearest_rank([30.0, 10.0, 20.0], 95) == 30.0,
         "P95 nearest-rank 算法错误"),
        (summary["tokens"]["prompt_total"] == 10
         and summary["tokens"]["completion_total"] == 4
         and summary["tokens"]["total"] == 14,
         "输入/输出 token 汇总错误"),
        (summary["fallback"]["count"] == 1
         and summary["fallback"]["rate"] == 1 / 3,
         "fallback 转人工率统计错误"),
    ]
    for passed, message in checks:
        if not passed:
            errors.append(message)

    trace = [
        {
            "name": "escalate_ticket",
            "arguments": '{"ticket_id": "T1005", "reason": "影响演示"}',
        }
    ]
    if not tool_trace_matches(trace, "escalate_ticket", {"ticket_id": "T1005"}):
        errors.append("工具名 + 关键参数匹配算法错误")
    if tool_trace_matches(trace, "get_ticket", {"ticket_id": "T1005"}):
        errors.append("工具名不同却被判为正确")

    no_basis = {
        "expect_no_basis": True,
        "expected_policy": None,
    }
    if not retrieval_matches(no_basis, []):
        errors.append("无答案样本在零引用时未判为正确")
    if retrieval_matches(no_basis, [{"policy_id": "P001"}]):
        errors.append("无答案样本制造伪引用却未被判错")
    return errors


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    records, errors = _load_records(TESTSET_PATH)
    for record in records:
        errors.extend(_check_record(record))
    errors.extend(_check_collection(records))
    errors.extend(_check_metric_algorithms())

    if errors:
        print(f"[FAIL] 评测集检查发现 {len(errors)} 个问题：")
        for error in errors:
            print(f"  - {error}")
        return 1

    counts = Counter(record["category"] for record in records)
    tools = Counter(
        record["expected_tool"]
        for record in records
        if record["expected_tool"] is not None
    )
    print("[OK] JSONL 格式、字段和 ID 全部合法")
    print(
        "[OK] 四层覆盖："
        f"政策 {counts['policy']} / 工单 {counts['ticket']} / "
        f"转人工 {counts['handoff']} / 边界 {counts['boundary']}"
    )
    print("[OK] 政策覆盖 P001–P004，无答案 2 条")
    print(
        "[OK] 工具覆盖："
        f"get_ticket {tools['get_ticket']} / "
        f"create_ticket {tools['create_ticket']} / "
        f"escalate_ticket {tools['escalate_ticket']}"
    )
    print("[OK] 工单初始数据前提与 seed.py 一致")
    print("[OK] 指标算法：意图 / 工具 / 检索 / P50-P95 / token / fallback")
    print("[OK] 评测集检查通过，共 20 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
