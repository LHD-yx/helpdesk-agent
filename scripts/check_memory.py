"""B1 离线自检：窗口 / 轮数 / TTL / 容量淘汰 / 并发。不调模型、不花钱。

用法（项目根目录）：
    python scripts\check_memory.py
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.memory.session_store import MAX_CONTENT_CHARS, SessionStore  # noqa: E402

CHECKS: list[tuple[str, callable]] = []


def check(fn: callable) -> callable:
    CHECKS.append((fn.__name__, fn))
    return fn


@check
def window_truncates() -> None:
    store = SessionStore(max_turns=6)
    for i in range(10):
        store.append("s1", "user", f"m{i}")
    turns = store.recent("s1", limit_turns=99)
    assert len(turns) == 6, f"窗口应保留 6 条，实际 {len(turns)}"
    assert turns[-1].content == "m9", "最新一条应在末尾"
    assert turns[0].content == "m4", "最旧的应被丢弃"


@check
def limit_turns_means_rounds() -> None:
    store = SessionStore(max_turns=20)
    for i in range(5):
        store.append("s2", "user", f"q{i}")
        store.append("s2", "assistant", f"a{i}")
    turns = store.recent("s2", limit_turns=2)
    assert len(turns) == 4, f"2 轮应为 4 条，实际 {len(turns)}"
    assert turns[-1].content == "a4"


@check
def ttl_expires() -> None:
    store = SessionStore(ttl_seconds=0.05)
    store.append("s3", "user", "hi")
    time.sleep(0.1)
    assert store.recent("s3") == [], "过期会话应返回空"
    assert len(store) == 0, "过期会话应被清理"


@check
def capacity_evicts_oldest() -> None:
    store = SessionStore(max_sessions=2, ttl_seconds=60)
    store.append("a", "user", "1")
    store.append("b", "user", "2")
    store.append("c", "user", "3")
    assert len(store) == 2, f"容量应限制为 2，实际 {len(store)}"
    assert store.recent("a") == [], "最久未活动的会话应被淘汰"
    assert len(store.recent("c")) == 1, "最新会话应保留"


@check
def content_truncated() -> None:
    store = SessionStore()
    store.append("s4", "user", "x" * 500)
    assert len(store.recent("s4")[0].content) == MAX_CONTENT_CHARS


@check
def concurrent_appends_are_safe() -> None:
    store = SessionStore(max_turns=6)

    def worker(n: int) -> None:
        for i in range(20):
            store.append("shared", "user", f"t{n}-{i}")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    turns = store.recent("shared", limit_turns=99)
    assert len(turns) == 6, f"并发后仍应只保留 6 条，实际 {len(turns)}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    passed = 0
    for name, fn in CHECKS:
        try:
            fn()
        except AssertionError as exc:
            print(f"[XX] {name} —— {exc}")
        except Exception as exc:  # 未处理异常同样算失败
            print(f"[XX] {name} —— 抛出了 {type(exc).__name__}: {exc}")
        else:
            print(f"[OK] {name}")
            passed += 1
    print(f"\n通过 {passed}/{len(CHECKS)}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
