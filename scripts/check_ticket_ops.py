"""工具循环的离线检查：用假模型驱动，不花 API 钱。

用法（项目根目录）：
    python scripts\check_ticket_ops.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.ticket_ops import run_tool_loop  # noqa: E402
from app.llm.base import LLMResult, ToolCall  # noqa: E402


class FakeChat:
    """按脚本依次返回 LLMResult，并记录每次收到的 messages。"""

    def __init__(self, script: list[LLMResult]) -> None:
        self.script = list(script)
        self.calls: list[list[dict]] = []

    def __call__(self, messages: list[dict], **kwargs) -> LLMResult:
        self.calls.append([dict(m) for m in messages])
        if not self.script:
            raise AssertionError("假模型的脚本用完了——循环调用次数超出预期")
        return self.script.pop(0)


def _ticket_call(ticket_id: str = "T1001", call_id: str = "call_abc") -> LLMResult:
    return LLMResult(
        tool_calls=[
            ToolCall(id=call_id, name="get_ticket", arguments=f'{{"ticket_id":"{ticket_id}"}}')
        ],
        finish_reason="tool_calls",
    )


def check_happy_path() -> None:
    fake = FakeChat([_ticket_call(), LLMResult(content="工单在处理中")])
    out = run_tool_loop("查工单 T1001", chat=fake)
    assert out["answer"] == "工单在处理中", out
    assert len(out["tool_calls"]) == 1, out
    assert out["stopped_by"] == "final_answer", out


def check_tool_call_id() -> None:
    fake = FakeChat([_ticket_call(call_id="call_abc"), LLMResult(content="好了")])
    run_tool_loop("查工单 T1001", chat=fake)

    second = fake.calls[1]
    tool_msgs = [m for m in second if m.get("role") == "tool"]
    assert tool_msgs, "第二轮请求里没有 role=tool 的消息"
    assert tool_msgs[-1].get("tool_call_id") == "call_abc", (
        f"tool_call_id 应该是 call_abc，实际是 {tool_msgs[-1].get('tool_call_id')!r}"
    )


def check_assistant_message_present() -> None:
    fake = FakeChat([_ticket_call(), LLMResult(content="好了")])
    run_tool_loop("查工单 T1001", chat=fake)
    roles = [m.get("role") for m in fake.calls[1]]
    assert roles == ["system", "user", "assistant", "tool"], f"消息顺序不对：{roles}"


def check_max_rounds() -> None:
    class AlwaysToolChat:
        def __init__(self) -> None:
            self.count = 0

        def __call__(self, messages: list[dict], **kwargs) -> LLMResult:
            self.count += 1
            if self.count > 10:
                raise AssertionError("循环没有上限：已经调用超过 10 次")
            return _ticket_call()

    out = run_tool_loop("查工单 T1001", max_rounds=3, chat=AlwaysToolChat())
    assert out["stopped_by"] == "max_rounds", f"应收口在 max_rounds，实际 {out['stopped_by']}"
    assert out["rounds"] == 3, f"轮数应为 3，实际 {out['rounds']}"


def check_bad_arguments() -> None:
    bad = LLMResult(
        tool_calls=[ToolCall(id="call_bad", name="get_ticket", arguments="T1001")],
        finish_reason="tool_calls",
    )
    fake = FakeChat([bad, LLMResult(content="参数好像有问题，请再发一次工单号")])
    out = run_tool_loop("查工单 T1001", chat=fake)

    assert out["tool_calls"], "没有任何工具调用记录"
    result = out["tool_calls"][0]["result"]
    assert result["ok"] is False, result
    assert result["error"] == "bad_arguments", result


CHECKS = [
    ("正常流程能拿到最终答案", check_happy_path),
    ("tool 消息的 id 来自 call.id", check_tool_call_id),
    ("assistant 消息在 tool 消息之前", check_assistant_message_present),
    ("轮数上限生效", check_max_rounds),
    ("坏参数不会让循环崩", check_bad_arguments),
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
