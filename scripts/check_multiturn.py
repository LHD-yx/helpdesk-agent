"""B3 验收：三条真实多轮对话 + 会话隔离。会调用模型，约 7 次请求。

用法（项目根目录）：
    python scripts\check_multiturn.py
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.orchestrator import handle_with_trace  # noqa: E402


def run(session_id: str, message: str):
    return handle_with_trace(message, session_id)


def tool_names(trace: dict) -> list[str]:
    return [c.get("name", "?") for c in trace.get("tool_calls", [])]


def tool_hits(trace: dict, name: str, needle: str) -> bool:
    for call in trace.get("tool_calls", []):
        if call.get("name") == name and needle in str(call.get("arguments", "")):
            return True
    return False


def show(idx: int, message: str, trace: dict) -> None:
    print(f"[轮 {idx}] {message}")
    print(
        f"   intent={trace['intent']:<10} conf={trace['confidence']:.2f} "
        f"history={trace['history_turns']}  tools={tool_names(trace) or '无'}"
    )
    print(f"   standalone={trace['standalone_query']!r}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    passed = 0
    total = 0

    def expect(label: str, ok: bool, detail: str = "") -> None:
        nonlocal passed, total
        total += 1
        passed += ok
        print(f"   {'[OK]' if ok else '[XX]'} {label}{' —— ' + detail if detail and not ok else ''}")

    # ---------------- 对话 1：工单追问 ----------------
    sid = f"mt-{uuid.uuid4().hex[:8]}"
    print("\n=== 对话 1：工单追问 ===")
    _, t1 = run(sid, "查一下工单 T1001")
    show(1, "查一下工单 T1001", t1)
    expect("第一轮走 ticket_op", t1["intent"] == "ticket_op", t1["intent"])
    expect("第一轮查到 T1001", tool_hits(t1, "get_ticket", "T1001"))
    expect("第一轮无历史", t1["history_turns"] == 0, str(t1["history_turns"]))

    _, t2 = run(sid, "它现在什么状态？")
    show(2, "它现在什么状态？", t2)
    expect("第二轮仍走 ticket_op", t2["intent"] == "ticket_op", t2["intent"])
    expect("第二轮回填了历史", t2["history_turns"] == 2, str(t2["history_turns"]))
    expect("指代被还原成 T1001", "T1001" in t2["standalone_query"], t2["standalone_query"])
    expect("第二轮查的是 T1001", tool_hits(t2, "get_ticket", "T1001"))

    # ---------------- 对话 2：政策追问 ----------------
    sid = f"mt-{uuid.uuid4().hex[:8]}"
    print("\n=== 对话 2：政策追问 ===")
    _, p1 = run(sid, "报销标准是多少")
    show(1, "报销标准是多少", p1)
    expect("第一轮走 policy_qa", p1["intent"] == "policy_qa", p1["intent"])

    resp2, p2 = run(sid, "那住宿呢？")
    show(2, "那住宿呢？", p2)
    expect("第二轮仍走 policy_qa", p2["intent"] == "policy_qa", p2["intent"])
    expect("指代被还原成住宿问题", "住宿" in p2["standalone_query"], p2["standalone_query"])
    expect("引用到 P001", any(c.policy_id == "P001" for c in resp2.citations),
           str([c.policy_id for c in resp2.citations]))

    # ---------------- 对话 3：语境切换 ----------------
    sid = f"mt-{uuid.uuid4().hex[:8]}"
    print("\n=== 对话 3：语境切换 ===")
    _, h1 = run(sid, "我要投诉")
    show(1, "我要投诉", h1)
    expect("第一轮转人工", h1["intent"] == "handoff", h1["intent"])

    _, h2 = run(sid, "那帮我查下 T1001")
    show(2, "那帮我查下 T1001", h2)
    expect("第二轮切回 ticket_op", h2["intent"] == "ticket_op", h2["intent"])
    expect("切换后仍查到 T1001", tool_hits(h2, "get_ticket", "T1001"))

    # ---------------- 会话隔离 ----------------
    print("\n=== 会话隔离：不同 session 不共享历史 ===")
    sid_a = f"iso-{uuid.uuid4().hex[:8]}"
    sid_b = f"iso-{uuid.uuid4().hex[:8]}"
    run(sid_a, "查一下工单 T1001")
    _, iso = run(sid_b, "它现在什么状态？")
    show(1, f"[{sid_b}] 它现在什么状态？", iso)
    expect("新会话没有历史", iso["history_turns"] == 0, str(iso["history_turns"]))
    expect("新会话看不到 T1001", "T1001" not in iso["standalone_query"], iso["standalone_query"])

    print(f"\n通过 {passed}/{total}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
