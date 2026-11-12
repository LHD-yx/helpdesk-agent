"""静态检查：前端必须走 HTTP，不能 import 后端代码。

用法（项目根目录）：
    python scripts\check_ui.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "ui" / "streamlit_app.py"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    if not UI.exists():
        print(f"[XX] 找不到 {UI}")
        return 1

    src = UI.read_text(encoding="utf-8")
    checks = [
        ("使用 requests.post 调 /chat", "requests.post" in src and "/chat" in src),
        ("没有 import 后端 app 包", "from app" not in src and "import app" not in src),
        ("渲染引用来源", "citations" in src),
        ("展示 request_id", "request_id" in src),
        ("展示降级状态", "fallback" in src),
        ("显示已知限制", "已知限制" in src),
    ]

    passed = 0
    for name, ok in checks:
        print(f"[{'OK' if ok else 'XX'}] {name}")
        passed += ok

    print(f"\n通过 {passed}/{len(checks)}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
