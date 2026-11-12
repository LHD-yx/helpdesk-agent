"""主编排：路由 → 三条真实分支 → 统一响应。

policy_qa 接 RAG，ticket_op 接 Function Calling，handoff 直接返回人工提示。
分支内部的降级通过 fallback / fallback_reason 传给调用方，不覆盖路由原判的
intent，保证评测测到的是真实路由结果。

handle() 额外负责：生成 request_id、计时、汇总各层降级与 token，
并在开始 / 结束各写一条结构化日志——一次请求的所有事件靠 request_id 串起来。
"""

from __future__ import annotations

from time import perf_counter

from app.agent.policy_qa import answer as policy_answer
from app.agent.router import classify
from app.agent.ticket_ops import run_tool_loop
from app.observability.logger import get_logger, log_event, new_request_id
from app.schemas import ChatResponse, Citation, Intent

logger = get_logger("orchestrator")


def handle(message: str, session_id: str = "default") -> ChatResponse:
    """一次对话的主流程（同步实现；Streamlit 通过 HTTP 调用它）。"""
    request_id = new_request_id()
    started = perf_counter()
    log_event(
        logger, "chat_start",
        request_id=request_id, session_id=session_id, message_chars=len(message),
    )

    route = classify(message)
    citations: list[Citation] = []
    served_by = route.served_by
    degraded = route.degraded
    prompt_tokens = route.prompt_tokens
    completion_tokens = route.completion_tokens
    fallback = False
    fallback_reason = ""

    if route.intent is Intent.HANDOFF:
        answer = f"这个问题需要人工协助，已为你转接。触发原因：{route.reason}"
    elif route.intent is Intent.TICKET_OP:
        # 工具循环：模型选工具 → 执行 → 结果回灌 → 生成答案。
        tool_result = run_tool_loop(message)
        answer = tool_result["answer"]
        served_by = tool_result.get("served_by") or served_by
        degraded = degraded or bool(tool_result.get("degraded"))
        prompt_tokens += tool_result.get("prompt_tokens", 0)
        completion_tokens += tool_result.get("completion_tokens", 0)
    else:
        result = policy_answer(message)
        answer = result.answer
        citations = [Citation(**c) for c in result.citations]
        fallback = result.fallback
        fallback_reason = result.fallback_reason
        served_by = result.served_by or served_by
        degraded = degraded or result.degraded
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens

    latency_ms = (perf_counter() - started) * 1000
    log_event(
        logger, "chat_done",
        request_id=request_id,
        intent=route.intent.value,
        confidence=route.confidence,
        fallback=fallback,
        fallback_reason=fallback_reason,
        served_by=served_by,
        degraded=degraded,
        citations=len(citations),
        latency_ms=round(latency_ms, 1),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
    )

    return ChatResponse(
        answer=answer,
        intent=route.intent,
        confidence=route.confidence,
        session_id=session_id,
        citations=citations,
        request_id=request_id,
        served_by=served_by,
        degraded=degraded,
        fallback=fallback,
        fallback_reason=fallback_reason,
    )
