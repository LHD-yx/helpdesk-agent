"""工具注册表。

模型只认 JSON Schema，不认 Python 函数。TOOL_SCHEMAS 描述参数，
REGISTRY 管名字到函数的映射，dispatch 把模型给的参数校验后送进去。
"""

from __future__ import annotations

import inspect
import json
from typing import Any, Callable

from app.tools.ticket_tools import (
    CATEGORIES,
    PRIORITIES,
    create_ticket,
    escalate_ticket,
    get_ticket,
)

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_ticket",
            "description": (
                "按工单号查询工单的状态、优先级、处理人和标题。"
                "用户提到 T 开头的编号，或问「我的工单怎么样了」时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "工单号，例如 T1001"},
                },
                "required": ["ticket_id"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_ticket",
            "description": (
                "新建一张工单。用户描述设备故障、行政或 IT 需求，"
                "且没有指定已有工单号时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "一句话概括问题"},
                    "description": {"type": "string", "description": "补充细节，可为空"},
                    "category": {
                        "type": "string",
                        "enum": list(CATEGORIES),
                        "description": "工单分类",
                    },
                    "priority": {
                        "type": "string",
                        "enum": list(PRIORITIES),
                        "description": "优先级",
                    },
                },
                "required": ["title"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "escalate_ticket",
            "description": (
                "升级一张已有工单，必须说明原因。"
                "用户要求加急、升级，或说「这事没人管」时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "string", "description": "要升级的工单号"},
                    "reason": {"type": "string", "description": "升级原因，一句话"},
                },
                "required": ["ticket_id", "reason"],
                "additionalProperties": False,
            },
        },
    },
]

REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {
    "get_ticket": get_ticket,
    "create_ticket": create_ticket,
    "escalate_ticket": escalate_ticket,
}


def _err(code: str, message: str) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message}


def dispatch(name: str, arguments: str) -> dict[str, Any]:
    """执行模型请求的工具，永远返回 dict。

    只翻译「模型给错了」这一类问题；函数内部的 TypeError / AttributeError
    属于我们自己的 bug，必须原样抛出，否则又被伪装成「模型抽风」。
    """
    fn = REGISTRY.get(name)
    if fn is None:
        return _err("unknown_tool", f"没有名为 {name} 的工具，可用：{sorted(REGISTRY)}")

    try:
        kwargs = json.loads(arguments or "{}")
    except json.JSONDecodeError as exc:
        return _err("bad_arguments", f"参数不是合法 JSON：{exc}")
    if not isinstance(kwargs, dict):
        return _err("bad_arguments", "参数必须是 JSON 对象")

    # 先按函数签名「试装」一遍：缺参数、多参数都在这拦下，
    # 这样就不用把 fn(**kwargs) 包进 try，避免吞掉函数内部的真 bug。
    try:
        inspect.signature(fn).bind(**kwargs)
    except TypeError as exc:
        return _err("bad_arguments", f"参数与工具定义不匹配：{exc}")

    return fn(**kwargs)
