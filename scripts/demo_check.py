"""录屏前的演示排练：三条场景，走真实 HTTP 链路。

用法（先起后端）：
    uvicorn app.main:app --port 8000
    python scripts\demo_check.py

可用环境变量 API_BASE 覆盖地址。
"""

from __future__ import annotations

import os
import sys
import time

import requests

API = os.getenv("API_BASE", "http://127.0.0.1:8000").rstrip("/")

# (问题, 期望意图, 答案里必须出现的片段, 是否必须有引用)
CASES = [
    ("出差住宿能报多少钱？", "policy_qa", "450", True),
    ("查工单 T1001", "ticket_op", None, False),
    ("我要投诉，转人工", "handoff", None, False),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    try:
        requests.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as exc:
        print(f"[!!] 后端不可用：{API}（{type(exc).__name__}）")
        print("     先运行：uvicorn app.main:app --port 8000")
        return 1

    passed = 0
    for i, (message, want_intent, must_contain, need_citation) in enumerate(CASES, 1):
        started = time.perf_counter()
        resp = requests.post(
            f"{API}/chat",
            json={"message": message, "session_id": "demo-check"},
            timeout=90,
        )
        elapsed = (time.perf_counter() - started) * 1000
        resp.raise_for_status()
        data = resp.json()

        intent_ok = data.get("intent") == want_intent
        text_ok = must_contain is None or must_contain in data.get("answer", "")
        cites = data.get("citations") or []
        cite_ok = bool(cites) is need_citation
        ok = intent_ok and text_ok and cite_ok
        passed += ok

        print(f"[{i}/{len(CASES)}] {'OK' if ok else 'XX'} {message}")
        print(
            f"      intent={data.get('intent')} "
            f"confidence={data.get('confidence', 0):.2f} "
            f"{elapsed:.0f}ms request_id={data.get('request_id')}"
        )
        if cites:
            print("      引用: " + " | ".join(
                f"{c['policy_id']} / {c['section']}" for c in cites
            ))
        else:
            print("      引用: 无")
        if not text_ok:
            print(f"      答案里没找到「{must_contain}」")

    print(f"\n演示场景通过 {passed}/{len(CASES)}")
    return 0 if passed == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
