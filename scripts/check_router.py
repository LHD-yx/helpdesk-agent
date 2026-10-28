"""路由离线自检：不调模型、不花钱，只验证解析与兜底逻辑。

用法（在项目根目录执行）：
    python scripts\check_router.py

和 check_db.py 一样，这是项目的常驻自检，不是一次性练习。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.router import (  # noqa: E402
    IntentResult,
    apply_policy,
    parse_result,
)
from app.schemas import Intent  # noqa: E402


def check_normal_json() -> None:
    r = parse_result('{"intent": "policy_qa", "confidence": 0.93, "reason": "询问制度"}')
    assert r.intent is Intent.POLICY_QA, f"intent 应为 policy_qa，实际 {r.intent}"
    assert abs(r.confidence - 0.93) < 1e-9, f"confidence 应保留 0.93，实际 {r.confidence}"


def check_uppercase_fence() -> None:
    raw = '```JSON\n{"intent": "ticket_op", "confidence": 0.9}\n```'
    r = parse_result(raw)
    assert r.intent is Intent.TICKET_OP, f"大写围栏没处理，得到 {r.intent}（{r.reason}）"


def check_bad_json() -> None:
    r = parse_result("抱歉，我无法判断这句话的意思")
    assert r.intent is Intent.HANDOFF, f"解析失败应转人工，实际 {r.intent}"
    assert r.confidence == 0.0, f"解析失败的置信度应为 0，实际 {r.confidence}"
    assert "解析失败" in r.reason, f"reason 要留下痕迹，实际 {r.reason!r}"


def check_invalid_intent() -> None:
    r = parse_result('{"intent": "policy", "confidence": 0.9}')
    assert r.intent is Intent.HANDOFF, f"非法枚举值应转人工，实际 {r.intent}"


def check_low_confidence() -> None:
    out = apply_policy(IntentResult(intent=Intent.POLICY_QA, confidence=0.4))
    assert out.intent is Intent.HANDOFF, f"低置信度应转人工，实际 {out.intent}"
    assert "0.40" in out.reason, f"reason 应保留原置信度，实际 {out.reason!r}"
    # 这一条专门防 "Intent.POLICY_QA.va" 这类拼接错误
    assert "policy_qa" in out.reason, f"reason 应保留原意图值，实际 {out.reason!r}"


def check_high_confidence() -> None:
    out = apply_policy(IntentResult(intent=Intent.TICKET_OP, confidence=0.85))
    assert out.intent is Intent.TICKET_OP, f"高置信度不该被改动，实际 {out.intent}"


CHECKS = [
    ("正常 JSON 能解析", check_normal_json),
    ("大写 JSON 围栏能剥掉", check_uppercase_fence),
    ("非法 JSON 转人工且留下原因", check_bad_json),
    ("非法枚举值转人工", check_invalid_intent),
    ("低置信度转人工并保留原值", check_low_confidence),
    ("高置信度保持原意图", check_high_confidence),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    passed = 0
    for name, fn in CHECKS:
        try:
            fn()
        except AssertionError as exc:
            print(f"[XX] {name} —— {exc}")
        except Exception as exc:
            print(f"[XX] {name} —— 抛出了未处理的 {type(exc).__name__}: {exc}")
        else:
            print(f"[OK] {name}")
            passed += 1

    print(f"\n通过 {passed}/{len(CHECKS)}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
