"""工单三件套：查、建、升级。

SQL 全部参数化；失败返回 {"ok": false, ...} 而不是抛异常，模型看到原因
才能自己改参数。枚举先在这里校验，直接把可选值告诉它，比撞数据库 CHECK
再冒一个 500 好处理。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.db.seed import connect

STATUSES = ("open", "in_progress", "resolved", "closed")
PRIORITIES = ("low", "normal", "high", "urgent")
CATEGORIES = ("IT", "行政", "财务", "人事", "采购", "其他")

DEFAULT_REQUESTER = "E005"  # 陈磊。真实系统应从登录态取，两周版写死并在答案里说明。


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _err(code: str, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": code, "message": message, **extra}


def _next_ticket_id(conn: Any) -> str:
    """T1001 → T1013 这种递增。单用户演示够用；并发下需要唯一索引 + 重试。"""
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(ticket_id, 2) AS INTEGER)) FROM tickets"
    ).fetchone()
    return f"T{(row[0] or 1000) + 1}"


GET_SQL = """
    SELECT t.*, r.name AS requester_name, a.name AS assignee_name
    FROM tickets AS t
    JOIN employees AS r ON r.employee_id = t.requester_id
    LEFT JOIN employees AS a ON a.employee_id = t.assignee_id
    WHERE t.ticket_id = ?
"""


def get_ticket(ticket_id: str) -> dict[str, Any]:
    """按工单号查一张工单。"""
    ticket_id = ticket_id.strip().upper()
    conn = connect()
    try:
        row = conn.execute(GET_SQL, (ticket_id,)).fetchone()
    finally:
        conn.close()

    if row is None:
        return _err("ticket_not_found", f"没有找到工单 {ticket_id}", ticket_id=ticket_id)
    return {"ok": True, "ticket": dict(row)}


def create_ticket(
    title: str,
    description: str = "",
    category: str = "IT",
    priority: str = "normal",
    requester_id: str = DEFAULT_REQUESTER,
) -> dict[str, Any]:
    """新建工单，返回完整记录。"""
    title = title.strip()
    if not title:
        return _err("empty_title", "工单标题不能为空")
    if category not in CATEGORIES:
        return _err("invalid_category", f"分类必须是 {CATEGORIES} 之一", got=category)
    if priority not in PRIORITIES:
        return _err("invalid_priority", f"优先级必须是 {PRIORITIES} 之一", got=priority)

    conn = connect()
    try:
        exists = conn.execute(
            "SELECT 1 FROM employees WHERE employee_id = ?", (requester_id,)
        ).fetchone()
        if exists is None:
            return _err("requester_not_found", f"员工 {requester_id} 不存在")

        ticket_id = _next_ticket_id(conn)
        now = _now()
        conn.execute(
            """INSERT INTO tickets
                   (ticket_id, title, description, status, priority, category,
                    requester_id, assignee_id, created_at, updated_at,
                    escalated_at, escalation_reason)
               VALUES (?, ?, ?, 'open', ?, ?, ?, NULL, ?, ?, NULL, NULL)""",
            (ticket_id, title, description.strip(), priority, category,
             requester_id, now, now),
        )
        conn.commit()
    finally:
        conn.close()

    return get_ticket(ticket_id)


def escalate_ticket(ticket_id: str, reason: str) -> dict[str, Any]:
    """升级工单：写入升级时间与原因，并把优先级提到 high。"""
    ticket_id = ticket_id.strip().upper()
    reason = reason.strip()
    if not reason:
        return _err("empty_reason", "升级必须说明原因")

    conn = connect()
    try:
        row = conn.execute(
            "SELECT status FROM tickets WHERE ticket_id = ?", (ticket_id,)
        ).fetchone()
        if row is None:
            return _err("ticket_not_found", f"没有找到工单 {ticket_id}", ticket_id=ticket_id)
        if row["status"] in ("resolved", "closed"):
            return _err(
                "ticket_closed",
                f"工单 {ticket_id} 已是 {row['status']} 状态，不能再升级",
                ticket_id=ticket_id,
            )

        now = _now()
        conn.execute(
            """UPDATE tickets
                  SET escalated_at = ?, escalation_reason = ?,
                      priority = 'high', updated_at = ?
                WHERE ticket_id = ?""",
            (now, reason, now, ticket_id),
        )
        conn.commit()
    finally:
        conn.close()

    return get_ticket(ticket_id)
