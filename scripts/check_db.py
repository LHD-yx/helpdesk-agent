"""Day2 数据层自检。

用法（必须在项目根目录执行）：
    python scripts/check_db.py

它做三段体检：
  1. 结构：表在不在、行数、外键完整性
  2. 约束：故意插三条坏数据，确认数据库真的把它们拒了（这是最容易被想当然的一步）
  3. 数据：种子数据是否满足 Day4/Day5 的演示需要

最后给一句人话结论。任何一项失败，退出码为 1。
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

# 让 scripts/ 下的脚本能找到项目根的 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.seed import DB_PATH, connect  # noqa: E402

TICKET_INSERT = """
    INSERT INTO tickets
        (ticket_id, title, description, status, priority, category,
         requester_id, assignee_id, created_at, updated_at,
         escalated_at, escalation_reason)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""

failures: list[str] = []
todos: list[str] = []


def report(label: str, ok: bool, detail: str = "", blocking: bool = True) -> None:
    mark = "[OK]" if ok else ("[!!]" if blocking else "[待办]")
    line = f"  {mark} {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not ok:
        (failures if blocking else todos).append(label)


def expect_reject(conn: sqlite3.Connection, label: str, row: tuple, keyword: str) -> None:
    """插一条坏数据，期望被数据库拒绝。用 SAVEPOINT 保证不留痕。"""
    conn.execute("SAVEPOINT probe")
    error: str | None = None
    try:
        conn.execute(TICKET_INSERT, row)
    except sqlite3.IntegrityError as exc:
        error = str(exc)
    finally:
        conn.execute("ROLLBACK TO probe")
        conn.execute("RELEASE probe")

    if error is None:
        report(label, False, "数据库没有拒绝，约束没生效")
    elif keyword.lower() not in error.lower():
        report(label, False, f"拒绝了，但原因不对：{error}")
    else:
        report(label, True, f"已拒绝（{error}）")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 62)
    print(f"数据库：{DB_PATH}")
    print("=" * 62)

    if not DB_PATH.exists():
        print("[!!] 数据库文件还不存在。请先跑：python -m app.db.seed")
        return 1

    conn = connect()

    # ---------------- 1. 结构 ----------------
    print("\n[1/3] 结构")
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    )}
    for name in ("employees", "tickets", "policies"):
        report(f"表 {name} 存在", name in tables)

    fk_on = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    report("外键开关已打开", fk_on == 1, f"PRAGMA foreign_keys = {fk_on}")

    orphan = conn.execute("PRAGMA foreign_key_check").fetchall()
    report("外键完整性", len(orphan) == 0, f"{len(orphan)} 条悬空引用")

    counts = {}
    for name in ("employees", "tickets", "policies"):
        counts[name] = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        print(f"         {name:<10} {counts[name]} 行")

    # ---------------- 2. 约束 ----------------
    print("\n[2/3] 约束（故意插坏数据，看数据库拦不拦）")
    base = ("2026-10-14 10:00", "2026-10-14 10:00")

    expect_reject(
        conn,
        "处理人不存在时被外键拒绝",
        ("PROBE-1", "探针", "", "open", "low", "IT", "E001", "E999", *base, None, None),
        "FOREIGN KEY",
    )
    expect_reject(
        conn,
        "状态写错时被 CHECK 拒绝",
        ("PROBE-2", "探针", "", "进行中", "low", "IT", "E001", None, *base, None, None),
        "CHECK",
    )
    expect_reject(
        conn,
        "升级字段只填一半时被 CHECK 拒绝",
        ("PROBE-3", "探针", "", "open", "low", "IT", "E001", None,
         *base, "2026-10-14 10:00", None),
        "CHECK",
    )

    # ---------------- 3. 数据 ----------------
    print("\n[3/3] 种子数据是否够 Day4/Day5 用")
    statuses = {r[0] for r in conn.execute("SELECT DISTINCT status FROM tickets")}
    missing = {"open", "in_progress", "resolved", "closed"} - statuses
    report("四种状态齐全", not missing, f"缺少 {sorted(missing)}" if missing else "")

    unassigned = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE assignee_id IS NULL"
    ).fetchone()[0]
    report("有未分配处理人的工单", unassigned > 0, f"{unassigned} 条")

    escalated = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE escalated_at IS NOT NULL"
    ).fetchone()[0]
    report("有升级过的工单", escalated > 0, f"{escalated} 条")

    bad_time = conn.execute(
        "SELECT COUNT(*) FROM tickets WHERE updated_at < created_at"
    ).fetchone()[0]
    report("更新时间不早于创建时间", bad_time == 0, f"{bad_time} 条异常")

    bad_escalation = conn.execute(
        """SELECT COUNT(*) FROM tickets
            WHERE escalated_at IS NOT NULL
              AND (escalated_at < created_at OR escalated_at > updated_at)"""
    ).fetchone()[0]
    report("升级时间落在创建与更新之间", bad_escalation == 0, f"{bad_escalation} 条异常")

    # 政策原文文件是否就位 —— 这条是 Day5 的前置，现在大概率还没写
    rows = conn.execute("SELECT policy_id, source_file FROM policies").fetchall()
    policy_dir = DB_PATH.parent / "policies"
    missing_files = [r["source_file"] for r in rows
                     if not (policy_dir / r["source_file"]).exists()]
    report(
        "政策原文文件就位",
        not missing_files,
        f"缺 {len(missing_files)} 份：{', '.join(missing_files)}" if missing_files else "",
        blocking=False,
    )

    conn.close()

    # ---------------- 结论 ----------------
    print("\n" + "=" * 62)
    if failures:
        print(f"结论：{len(failures)} 项不通过 → {failures}")
    else:
        print("结论：数据层健康 ✓")
    if todos:
        print(f"待办：{todos}")
    print("=" * 62)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
