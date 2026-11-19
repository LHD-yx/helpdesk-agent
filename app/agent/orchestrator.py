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
from app.memory.session_store import SessionStore
from app.observability.logger import get_logger, log_event, new_request_id
from app.schemas import ChatResponse, Citation, Intent

logger = get_logger("orchestrator")

# 进程内单例。多 worker 部署时不共享——这条写进 README 的已知限制。
memory = SessionStore()


def handle_with_trace(
    message: str, session_id: str = ""
) -> tuple[ChatResponse, dict]:
    """一次对话的主流程，并返回本次的链路信息（给评测/调试用）。"""
    sid = session_id.strip()
    use_memory = bool(sid)
    history = memory.recent(sid, limit_turns=3) if use_memory else []

    request_id = new_request_id()
    started = perf_counter()
    log_event(
        logger, "chat_start",
        request_id=request_id, session_id=session_id, message_chars=len(message),
        history_turns=len(history),
    )

    route = classify(message, history)
    # 只有多轮才用改写结果。首轮强制用原句：
    # 一是模型并不总听话（实测会自作主张润色），二是保住 20 条单轮评测的输入不变。
    if history:
        query = (route.standalone_query or "").strip() or message
    else:
        query = message

    citations: list[Citation] = []
    tool_trace: list[dict] = []
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
        tool_result = run_tool_loop(query)
        answer = tool_result["answer"]
        tool_trace = tool_result.get("tool_calls", [])
        served_by = tool_result.get("served_by") or served_by
        degraded = degraded or bool(tool_result.get("degraded"))
        prompt_tokens += tool_result.get("prompt_tokens", 0)
        completion_tokens += tool_result.get("completion_tokens", 0)
    else:
        result = policy_answer(query)
        answer = result.answer
        citations = [Citation(**c) for c in result.citations]
        fallback = result.fallback
        fallback_reason = result.fallback_reason
        served_by = result.served_by or served_by
        degraded = degraded or result.degraded
        prompt_tokens += result.prompt_tokens
        completion_tokens += result.completion_tokens

    if use_memory:
        # 存用户原话，不存改写后的问句——下一轮的上下文才是真实对话。
        memory.append(sid, "user", message)
        memory.append(sid, "assistant", answer)

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
        rewritten=query != message,
    )

    response = ChatResponse(
        answer=answer,
        intent=route.intent,
        confidence=route.confidence,
        session_id=sid or f"anon-{request_id}",
        citations=citations,
        request_id=request_id,
        served_by=served_by,
        degraded=degraded,
        fallback=fallback,
        fallback_reason=fallback_reason,
    )
    trace = {
        "request_id": request_id,
        "intent": route.intent.value,
        "confidence": route.confidence,
        "standalone_query": query,
        "history_turns": len(history),
        "tool_calls": tool_trace,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "latency_ms": round(latency_ms, 1),
    }
    return response, trace


def handle(message: str, session_id: str = "") -> ChatResponse:
    """对外的主流程（FastAPI / 脚本都调这个）。"""
    return handle_with_trace(message, session_id)[0]
