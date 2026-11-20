"""交接单自检：离线（临时库）验证表结构与写入逻辑，再做一次真实链路集成。

用法（项目根目录）：
    python scripts\check_handoff.py

集成部分会真实调用一次路由（约 1–2 秒），并在 data/helpdesk.db 写一条交接单。
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.agent.handoff as handoff  # noqa: E402
from app.config import BASE_DIR  # noqa: E402

SCHEMA = BASE_DIR / "app" / "db" / "schema.sql"


def _temp_connect(path: Path):
    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    return connect


def check_offline() -> int:
    passed = 0
    original = handoff.connect
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "handoff_test.db"
        conn = _temp_connect(db_path)()
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        conn.close()
        handoff.connect = _temp_connect(db_path)

        try:
            route = handoff.create_handoff(
                session_id="s1", message="我要投诉", reason="投诉需人工",
                source="route", intent="handoff",
                context=[{"role": "user", "content": "我要投诉"}],
            )
            assert route["handoff_id"] == "H0001", route["handoff_id"]
            assert route["status"] == "pending", route["status"]
            assert route["source"] == "route", route["source"]
            print("[OK] 路由转人工生成 H0001，状态 pending")
            passed += 1

            fallback = handoff.create_handoff(
                session_id="s1", message="有搬家补贴吗", reason="no_policy_hit",
                source="fallback", intent="policy_qa", context=[],
            )
            assert fallback["handoff_id"] == "H0002", fallback["handoff_id"]
            assert fallback["source"] == "fallback", fallback["source"]
            print("[OK] 检索降级生成 H0002，source=fallback")
            passed += 1

            rows = handoff.list_handoffs(status="pending")
            assert [r["handoff_id"] for r in rows] == ["H0002", "H0001"], rows
            print("[OK] 待处理列表按最新在前返回 2 条")
            passed += 1

            detail = handoff.get_handoff("h0001")
            assert detail is not None and detail["context"][0]["content"] == "我要投诉"
            print("[OK] 详情可按小写编号查询，上下文完整")
            passed += 1

            for kwargs in (
                dict(source="bogus"),
                dict(status="bogus"),
            ):
                try:
                    if "source" in kwargs:
                        handoff.create_handoff(
                            session_id="s1", message="x", reason="x",
                            source=kwargs["source"], intent="handoff",
                        )
                    else:
                        handoff.list_handoffs(status=kwargs["status"])
                except ValueError:
                    continue
                raise AssertionError(f"非法参数未被拒绝：{kwargs}")
            print("[OK] 非法 source / status 被拒绝")
            passed += 1

            raw = sqlite3.connect(db_path)
            try:
                raw.execute(
                    "INSERT INTO handoffs (handoff_id, session_id, message, reason, "
                    "source, intent, created_at) VALUES "
                    "('H9999','s','x','x','bogus','handoff','2026-11-20 00:00')"
                )
            except sqlite3.IntegrityError:
                print("[OK] 数据库 CHECK 兜底：非法 source 无法入库")
                passed += 1
            else:
                raise AssertionError("数据库没有拒绝非法 source")
            finally:
                raw.close()
        finally:
            handoff.connect = original

    return passed


def check_integration() -> int:
    from app.agent.orchestrator import handle

    response = handle("我要投诉行政前台的服务态度", session_id="check-handoff")
    assert response.intent.value == "handoff", response.intent
    assert response.handoff_id, "转人工没有生成交接单号"

    record = handoff.get_handoff(response.handoff_id)
    assert record is not None, "交接单写入后查不到"
    assert record["source"] == "route", record["source"]
    assert record["status"] == "pending", record["status"]
    print(f"[OK] 真实链路：投诉 → {response.handoff_id}，"
          f"source={record['source']}，status={record['status']}")
    return 1


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    passed = check_offline()
    passed += check_integration()
    print(f"\n通过 {passed}/7")
    return 0 if passed == 7 else 1


if __name__ == "__main__":
    raise SystemExit(main())
