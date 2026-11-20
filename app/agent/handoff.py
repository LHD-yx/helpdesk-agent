"""人工交接单：把“转人工”从一句提示变成一条可查询的记录。

两条写入路径：
  route     路由层直接判为 handoff（投诉 / 超范围 / 低置信度）
  fallback  进了政策分支，但检索不到可引用依据

为什么落库而不是只返回提示：
  用户关掉页面后，这次交接就消失了。落库之后人工侧能按 status 拉待处理，
  也能复盘「哪类问题最常被转人工」——这是产品改进的输入。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.db.seed import connect

SOURCES = ("route", "fallback")
STATUSES = ("pending", "claimed", "closed")
MAX_CONTEXT_CHARS = 2000


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _next_id(conn: Any) -> str:
    """H0001 起递增。单用户演示够用；并发下需要唯一索引 + 重试。"""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(handoff_id, 2) AS INTEGER)) FROM handoffs"
    ).fetchone()
    return f"H{(row[0] or 0) + 1:04d}"


def create_handoff(
    *,
    session_id: str,
    message: str,
    reason: str,
    source: str,
    intent: str,
    context: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """写入一条待处理交接单，返回完整记录。"""
    if source not in SOURCES:
        raise ValueError(f"source 必须是 {SOURCES} 之一，收到 {source!r}")

    payload = json.dumps(context or [], ensure_ascii=False)[:MAX_CONTEXT_CHARS]
    conn = connect()
    try:
        handoff_id = _next_id(conn)
        conn.execute(
            """INSERT INTO handoffs
                   (handoff_id, session_id, message, reason, source,
                    intent, context, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (
                handoff_id,
                session_id[:64],
                message[:2000],
                reason[:500],
                source,
                intent,
                payload,
                _now(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM handoffs WHERE handoff_id = ?", (handoff_id,)
        ).fetchone()
    finally:
        conn.close()

    return dict(row)


def list_handoffs(
    *, status: str | None = None, limit: int = 20
) -> list[dict[str, Any]]:
    """按状态拉交接单，最新的在前。不返回 context，避免列表过大。"""
    if status is not None and status not in STATUSES:
        raise ValueError(f"status 必须是 {STATUSES} 之一，收到 {status!r}")
    limit = max(1, min(int(limit), 200))

    sql = (
        "SELECT handoff_id, session_id, message, reason, source, intent, "
        "status, created_at FROM handoffs"
    )
    params: list[Any] = []
    if status is not None:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC, handoff_id DESC LIMIT ?"
    params.append(limit)

    conn = connect()
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def get_handoff(handoff_id: str) -> dict[str, Any] | None:
    """取单条交接单，包含最近对话上下文。"""
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM handoffs WHERE handoff_id = ?", (handoff_id.strip().upper(),)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None

    record = dict(row)
    try:
        record["context"] = json.loads(record.get("context") or "[]")
    except json.JSONDecodeError:
        record["context"] = []
    return record
