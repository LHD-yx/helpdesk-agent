"""结构化日志：一行一个 JSON 事件。

为什么自己写这 40 行，而不是引 structlog：
  标准库 logging 已经够用，格式化器只做三件事——补时间、补级别、把业务字段摊平。
  少一个依赖，面试被问"这一行日志怎么来的"时也能从第一行讲到最后一行。
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from datetime import datetime
from typing import Any

ROOT_LOGGER = "helpdesk"
_configured = False


class JsonFormatter(logging.Formatter):
    """把 LogRecord 拍平成一个 JSON 对象。"""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    """只配置一次；重复调用不会叠加 handler。"""
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger(ROOT_LOGGER)
    root.handlers.clear()          # 防止 uvicorn --reload 下重复挂载
    root.addHandler(handler)
    root.setLevel(level.upper())
    root.propagate = False         # 不要冒泡到根 logger，避免同一行打两遍
    _configured = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def new_request_id() -> str:
    """短 ID 就够用：一次请求内唯一，日志里好读。"""
    return uuid.uuid4().hex[:12]


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    """打一条结构化事件。字段名用下划线，和 Python 习惯一致。"""
    logger.info(event, extra={"fields": {"event": event, **fields}})
