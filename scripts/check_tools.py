"""B2 离线自检：注册表一致性 + dispatch 容错。不调模型、不写库。

用法（项目根目录）：
    python scripts\check_tools.py
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.tools.registry import REGISTRY, TOOL_SCHEMAS, dispatch  # noqa: E402


def check_schema_matches_registry() -> None:
    names = {item["function"]["name"] for item in TOOL_SCHEMAS}
    assert names == set(REGISTRY), f"Schema 与注册表不一致：{names} vs {set(REGISTRY)}"
    for item in TOOL_SCHEMAS:
        params = item["function"]["parameters"]
        assert params["type"] == "object"
        assert params["required"], f"{item['function']['name']} 没有 required 字段"


def check_schema_matches_signature() -> None:
    """契约检查：Schema 声明的参数，必须真的存在于函数签名里。

    这条检查专门防「Schema 写 ticketId、函数是 ticket_id」这种错——
    它不会让离线 dispatch 测试挂，但会让线上每次调用都返回 bad_arguments。
    """
    for item in TOOL_SCHEMAS:
        name = item["function"]["name"]
        params = item["function"]["parameters"]
        sig = inspect.signature(REGISTRY[name])

        for prop in params["properties"]:
            assert prop in sig.parameters, (
                f"{name}: Schema 声明了参数 {prop!r}，函数签名里没有"
                f"（实际参数：{list(sig.parameters)}）"
            )

        for req in params["required"]:
            assert req in params["properties"], (
                f"{name}: required 里的 {req!r} 不在 properties 里"
            )
            assert sig.parameters[req].default is inspect.Parameter.empty, (
                f"{name}: {req!r} 标成 required，但函数里有默认值"
            )


def check_normal_call() -> None:
    result = dispatch("get_ticket", '{"ticket_id": "T1001"}')
    assert result["ok"] is True, result
    assert result["ticket"]["status"] == "in_progress", result


def check_unknown_tool() -> None:
    result = dispatch("delete_everything", "{}")
    assert result["ok"] is False and result["error"] == "unknown_tool", result


def check_bad_json() -> None:
    result = dispatch("get_ticket", "T1001")
    assert result["ok"] is False and result["error"] == "bad_arguments", result


def check_missing_argument() -> None:
    result = dispatch("get_ticket", "{}")
    assert result["ok"] is False and result["error"] == "bad_arguments", result


def check_extra_argument() -> None:
    result = dispatch("get_ticket", '{"ticket_id": "T1001", "force": true}')
    assert result["ok"] is False and result["error"] == "bad_arguments", result


def check_business_error_passthrough() -> None:
    result = dispatch("escalate_ticket", '{"ticket_id": "T1001", "reason": "  "}')
    assert result["ok"] is False and result["error"] == "empty_reason", result


CHECKS = [
    ("Schema 与注册表一致", check_schema_matches_registry),
    ("Schema 参数名与函数签名一致", check_schema_matches_signature),
    ("正常调用 get_ticket", check_normal_call),
    ("未知工具被拒绝", check_unknown_tool),
    ("非法 JSON 被拒绝", check_bad_json),
    ("缺参数被拒绝", check_missing_argument),
    ("多参数被拒绝", check_extra_argument),
    ("业务错误原样透传", check_business_error_passthrough),
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
