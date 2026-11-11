"""最小编排：路由 → 三条真实分支 → 统一响应。

policy_qa 接 RAG，ticket_op 接 Function Calling，handoff 直接返回人工提示。
分支内部的降级通过 fallback / fallback_reason 传给调用方，不覆盖路由原判的
intent，保证评测测到的是真实路由结果。
"""

from __future__ import annotations

from app.agent.policy_qa import answer as policy_answer
from app.agent.router import classify
from app.agent.ticket_ops import run_tool_loop
from app.schemas import ChatResponse, Citation, Intent


def handle(message: str, session_id: str = "default") -> ChatResponse:
    """一次对话的主流程。今天是同步的，D5 前端接上时可能需要改成异步。"""
    route = classify(message)
    citations: list[Citation] = []
    fallback = False
    fallback_reason = ""

    if route.intent is Intent.HANDOFF:
        answer = f"这个问题需要人工协助，已为你转接。触发原因：{route.reason}"
    elif route.intent is Intent.TICKET_OP:
        # 真正的工具循环：模型选工具 → 执行 → 结果回灌 → 生成答案。
        answer = run_tool_loop(message)["answer"]
    else:
        result = policy_answer(message)
        answer = result.answer
        citations = [Citation(**c) for c in result.citations]
        fallback = result.fallback
        fallback_reason = result.fallback_reason

    return ChatResponse(
        answer=answer,
        intent=route.intent,
        confidence=route.confidence,
        session_id=session_id,
        citations=citations,
        fallback=fallback,
        fallback_reason=fallback_reason,
    )
