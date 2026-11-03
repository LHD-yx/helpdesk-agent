"""B1 离线验收：直接调三个工具，不经过模型。

用法（项目根目录）：
    python scripts\smoke_tools.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.ticket_tools import (  # noqa: E402
    create_ticket,
    escalate_ticket,
    get_ticket,
)


def show(label: str, result: dict) -> None:
    if result["ok"]:
        ticket = result["ticket"]
        print(
            f"[OK] {label} → {ticket['ticket_id']} | {ticket['status']} | "
            f"{ticket['priority']} | {ticket['title']}"
        )
    else:
        print(f"[--] {label} → {result['error']}：{result['message']}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    show("查存在的工单", get_ticket("T1001"))
    show("查不存在的工单", get_ticket("T9999"))

    created = create_ticket(
        title="B1 冒烟：打印机又坏了",
        description="三楼打印机报错，需要现场处理",
        category="IT",
        priority="normal",
    )
    show("新建工单", created)
    if created["ok"]:
        show("回查新建的工单", get_ticket(created["ticket"]["ticket_id"]))

    show("升级未关闭的工单", escalate_ticket("T1005", "影响演示，需要当日闭环"))
    show("升级已关闭的工单", escalate_ticket("T1010", "测试非法升级"))
    show("升级原因留空", escalate_ticket("T1005", "   "))

    print("\n说明：本次新建的工单会真实写进 data/helpdesk.db，这是验收要求。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
