"""多步任务验收：验证模型能连续调用多个工具，并把结果汇总成人话。

用法（项目根目录）：
    python evals\run_multistep.py

注意：会真实升级工单（写 data/helpdesk.db），这是验收要求。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.orchestrator import handle_with_trace  # noqa: E402

CASES_PATH = Path(__file__).with_name("multistep.jsonl")


def _args(call: dict) -> dict:
    raw = call.get("arguments") or "{}"
    try:
        return json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def _match_in_order(trace: list[dict], expected: list[dict]) -> tuple[bool, int]:
    """期望的工具按顺序出现即可，中间允许有多余调用。"""
    idx = 0
    for call in trace:
        if idx >= len(expected):
            break
        exp = expected[idx]
        if call.get("name") != exp["name"]:
            continue
        actual = _args(call)
        if all(str(actual.get(k)) == str(v) for k, v in exp.get("args", {}).items()):
            idx += 1
    return idx == len(expected), idx


def _match_any_order(trace: list[dict], expected: list[dict]) -> tuple[bool, int]:
    """不要求顺序：每条期望工具都能在轨迹里找到一条未被使用的匹配。"""
    used: set[int] = set()
    matched = 0
    for exp in expected:
        for i, call in enumerate(trace):
            if i in used or call.get("name") != exp["name"]:
                continue
            actual = _args(call)
            if all(str(actual.get(k)) == str(v) for k, v in exp.get("args", {}).items()):
                used.add(i)
                matched += 1
                break
    return matched == len(expected), matched


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cases = [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    passed = 0
    for case in cases:
        response, trace = handle_with_trace(
            case["message"], session_id=f"multistep-{case['id']}"
        )
        tool_trace = trace["tool_calls"]
        matcher = _match_in_order if case.get("ordered", True) else _match_any_order
        sequence_ok, matched = matcher(tool_trace, case["expected_tools"])
        intent_ok = response.intent.value == case["expected_intent"]
        missing = [word for word in case["must_mention"] if word not in response.answer]
        ok = intent_ok and sequence_ok and not missing
        passed += ok

        print(f"[{'OK' if ok else 'XX'}] {case['id']} {case['message']}")
        order_label = "顺序" if case.get("ordered", True) else "任意顺序"
        print(f"     intent={response.intent.value} {'✓' if intent_ok else '✗'}"
              f"  工具匹配（{order_label}）{matched}/{len(case['expected_tools'])}"
              f" {'✓' if sequence_ok else '✗'}")
        for i, step in enumerate(response.steps, 1):
            print(f"     {i}. {step.action} — {step.detail}")
        if missing:
            print(f"     答案缺少关键信息：{missing}")
        print(f"     答案：{response.answer.replace(chr(10), ' ')[:100]}")
        print()

    print(f"多步任务通过 {passed}/{len(cases)}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
