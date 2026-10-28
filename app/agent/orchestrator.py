"""最小编排：路由 → 三条分支 → 统一响应。

D1 的三条分支都是桩（stub）：
  policy_qa → D3 接 RAG
  ticket_op → D2 接 Function Calling
  handoff   → 已经可用（转人工不需要业务数据）

为什么要先做桩：先把 HTTP → 路由 → 分支 → 返回 这条细线打通，
后面每接一块真业务，只换对应的桩，不用动链路结构。
"""

from __future__ import annotations

from app.agent.router import classify
from app.schemas import ChatResponse, Intent

STUB_ANSWERS: dict[Intent, str] = {
    Intent.POLICY_QA: "（桩）政策分支待 D3 接入检索，今天先返回占位答案。",
    Intent.TICKET_OP: "（桩）工单分支待 D2 接入工具，今天先返回占位答案。",
}


def handle(message: str, session_id: str = "default") -> ChatResponse:
    """一次对话的主流程。今天是同步的，D5 前端接上时可能需要改成异步。"""
    route = classify(message)

    if route.intent is Intent.HANDOFF:
        answer = f"这个问题需要人工协助，已为你转接。触发原因：{route.reason}"
    else:
        answer = STUB_ANSWERS[route.intent]

    return ChatResponse(
        answer=answer,
        intent=route.intent,
        confidence=route.confidence,
        session_id=session_id,
    )
