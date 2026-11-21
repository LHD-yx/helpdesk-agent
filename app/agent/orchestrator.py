"""一次对话的主流程：取记忆 → 路由 → 走对应分支 → 汇总 → 写日志。

分支里的降级只往上带 fallback / fallback_reason，不改 route.intent。
之前为了"看起来一致"改写过一次，结果评测里路由的错判全被掩盖了，
之后就固定成现在这样。request_id 在入口生成，路由、工具、生成几段日志都靠它串。
"""

from __future__ import annotations

import json
import sqlite3
from time import perf_counter
from typing import Any

from app.agent.handoff import create_handoff
from app.agent.policy_qa import answer as policy_answer
from app.agent.router import classify
from app.agent.ticket_ops import run_tool_loop
from app.memory.session_store import SessionStore
from app.observability.logger import get_logger, log_event, new_request_id
from app.schemas import ChatResponse, Citation, Intent, Step

logger = get_logger("orchestrator")

# 进程内单例。多 worker 部署时不共享——这条写进 README 的已知限制。
memory = SessionStore()


def _tool_step(call: dict[str, Any]) -> Step:
    """把一条工具调用翻译成给人看的一步。"""
    name = call.get("name", "unknown")
    raw_args = call.get("arguments") or "{}"
    try:
        args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
    except (json.JSONDecodeError, TypeError, ValueError):
        args = {}
    result = call.get("result") or {}
    ok = bool(result.get("ok", True))

    if name == "get_ticket":
        tid = args.get("ticket_id", "?")
        if ok:
            ticket = result.get("ticket", {})
            return Step(
                action=name,
                detail=f"查询工单 {tid}：{ticket.get('status', '?')} / 优先级 {ticket.get('priority', '?')}",
            )
        return Step(action=name, detail=f"查询工单 {tid}：{result.get('message', '未找到')}", ok=False)

    if name == "create_ticket":
        if ok:
            ticket = result.get("ticket", {})
            return Step(
                action=name,
                detail=f"新建工单 {ticket.get('ticket_id', '?')}：{ticket.get('title', '')[:20]}",
            )
        return Step(action=name, detail=f"新建工单失败：{result.get('message', '')}", ok=False)

    if name == "escalate_ticket":
        tid = args.get("ticket_id", "?")
        if ok:
            return Step(action=name, detail=f"升级工单 {tid}：优先级提升为 high")
        return Step(action=name, detail=f"升级工单 {tid} 失败：{result.get('message', '')}", ok=False)

    return Step(action=name, detail=f"调用工具 {name}", ok=ok)


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
    steps: list[Step] = []
    served_by = route.served_by
    degraded = route.degraded
    prompt_tokens = route.prompt_tokens
    completion_tokens = route.completion_tokens
    fallback = False
    fallback_reason = ""

    if route.intent is Intent.HANDOFF:
        answer = f"这个问题需要人工协助，已为你转接。触发原因：{route.reason}"
        steps = [Step(action="handoff", detail=f"转人工：{route.reason or '模型判断不适合自动作答'}")]
    elif route.intent is Intent.TICKET_OP:
        # 工具循环：模型选工具 → 执行 → 结果回灌 → 生成答案。
        tool_result = run_tool_loop(query)
        answer = tool_result["answer"]
        tool_trace = tool_result.get("tool_calls", [])
        served_by = tool_result.get("served_by") or served_by
        degraded = degraded or bool(tool_result.get("degraded"))
        prompt_tokens += tool_result.get("prompt_tokens", 0)
        completion_tokens += tool_result.get("completion_tokens", 0)
        steps = [_tool_step(call) for call in tool_trace]
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
        if citations:
            steps = [
                Step(
                    action="retrieve_policy",
                    detail=f"检索政策库：命中 {len(citations)} 段，生成带引用回答",
                )
            ]
        else:
            steps = [
                Step(
                    action="retrieve_policy",
                    detail="检索政策库：没有找到可引用的依据，转人工",
                    ok=False,
                )
            ]

    if use_memory:
        # 存用户原话，不存改写后的问句——下一轮的上下文才是真实对话。
        memory.append(sid, "user", message)
        memory.append(sid, "assistant", answer)

    # 转人工不能止于一句提示：落一条交接单，人工侧才能真的接手。
    handoff_id = ""
    if route.intent is Intent.HANDOFF or fallback:
        source = "route" if route.intent is Intent.HANDOFF else "fallback"
        reason = route.reason if source == "route" else (fallback_reason or "unknown")
        try:
            record = create_handoff(
                session_id=sid or f"anon-{request_id}",
                message=message,
                reason=reason or "未提供原因",
                source=source,
                intent=route.intent.value,
                context=[
                    {"role": turn.role, "content": turn.content} for turn in history
                ],
            )
            handoff_id = record["handoff_id"]
            steps.append(
                Step(action="handoff_record", detail=f"生成交接单 {handoff_id}，等待人工接手")
            )
            log_event(
                logger, "handoff_created",
                request_id=request_id, handoff_id=handoff_id, source=source,
            )
        except sqlite3.Error as exc:
            # 交接单写失败不该让用户拿不到回答；但必须留下告警，不能静默。
            log_event(
                logger, "handoff_failed", request_id=request_id, error=str(exc)[:200]
            )

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
        steps=steps,
        request_id=request_id,
        served_by=served_by,
        degraded=degraded,
        fallback=fallback,
        fallback_reason=fallback_reason,
        handoff_id=handoff_id,
    )
    trace = {
        "request_id": request_id,
        "intent": route.intent.value,
        "confidence": route.confidence,
        "standalone_query": query,
        "history_turns": len(history),
        "tool_calls": tool_trace,
        "steps": [step.model_dump() for step in steps],
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "handoff_id": handoff_id,
        "latency_ms": round(latency_ms, 1),
    }
    return response, trace


def handle(message: str, session_id: str = "") -> ChatResponse:
    """对外的主流程（FastAPI / 脚本都调这个）。"""
    return handle_with_trace(message, session_id)[0]
