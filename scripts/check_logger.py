"""离线检查：结构化日志（不联网、不花钱）。

用法（项目根目录）：
    python scripts\check_logger.py
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.observability.logger import (  # noqa: E402
    JsonFormatter,
    log_event,
    new_request_id,
)


def capture_events() -> list[dict]:
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())

    logger = logging.getLogger("helpdesk.check")
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel("INFO")
    logger.propagate = False

    rid = new_request_id()
    log_event(logger, "chat_start", request_id=rid, message="申请生产数据库权限")
    log_event(logger, "tool_call", request_id=rid, tool="get_ticket", ok=True)
    log_event(
        logger,
        "chat_done",
        request_id=rid,
        intent="policy_qa",
        confidence=0.95,
        latency_ms=2146.3,
        total_tokens=1524,
        fallback=False,
    )

    lines = [line for line in buf.getvalue().splitlines() if line.strip()]
    for line in lines:
        print(line)
    return [json.loads(line) for line in lines]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    events = capture_events()

    checks = [
        ("三行都是合法 JSON", len(events) == 3),
        ("request_id 贯穿三条事件", len({e["request_id"] for e in events}) == 1),
        ("中文未被转义", any("申请" in str(e.get("message", "")) for e in events)),
        ("必含 ts / level / event", all({"ts", "level", "event"} <= set(e) for e in events)),
        (
            "chat_done 带齐验收字段",
            {"request_id", "intent", "latency_ms", "total_tokens", "fallback"}
            <= set(events[-1]),
        ),
    ]

    print()
    passed = 0
    for name, ok in checks:
        print(f"[{'OK' if ok else 'XX'}] {name}")
        passed += ok
    print(f"\n通过 {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
