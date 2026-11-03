"""B3 验收：让模型真的走一遍工具循环。

用法（项目根目录）：
    python scripts\smoke_ticket_ops.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.ticket_ops import run_tool_loop  # noqa: E402

CASES = [
    "查工单 T1001",
    "查工单 T9999",
    "把 T1005 升级一下，影响今天演示",
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    for i, message in enumerate(CASES, 1):
        print(f"\n===== {i}. {message}")
        out = run_tool_loop(message)
        print(f"轮数={out['rounds']} 收口方式={out['stopped_by']}")
        for call in out["tool_calls"]:
            print(f"  调用 {call['name']}({call['arguments']})")
            print(f"  结果 {call['result'].get('ok')} {call['result'].get('error', '')}")
        print(f"回答：{out['answer']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
