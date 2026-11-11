"""工单分支：让模型通过「工具循环」完成一次工单操作。

循环的本质只有一句话：
    模型要调工具 → 我们执行 → 把结果作为一条消息喂回去 → 模型继续。
"""

from __future__ import annotations

import json
from typing import Any, Callable

from app.llm import LLMResult, get_llm_service
from app.tools.registry import TOOL_SCHEMAS, dispatch

MAX_ROUNDS = 3

SYSTEM_PROMPT = """你是企业服务台的工单助手。

规则：
1. 需要工单数据时先调用工具，不要凭猜测回答。
2. 拿到工具结果后，用中文向用户解释结果。
3. 工具返回 ok=false 时，把原因翻译成用户能听懂的话，并给出下一步建议。
4. 不要编造工单号、状态或处理人。
5. 用户给出了工单号并明确要求查询、升级、加急或继续处理时，先调用对应工具，
   不要自行预判业务规则，也不要先要求用户二次确认；是否允许由工具结果决定。
   即使工单已关闭，也应实际发起升级请求，再把工具返回的拒绝原因转告用户。
"""


def _assistant_tool_message(resp: LLMResult) -> dict[str, Any]:
    """把模型的 tool_calls 还原成 OpenAI 协议要求的 assistant 消息。

    这一步不能省：对话历史里必须先有「模型请求调用工具」这条消息，
    后面的 role="tool" 结果才有归属。少了它，模型会重复调同一个工具。
    """
    return {
        "role": "assistant",
        "content": resp.content or "",
        "tool_calls": [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in resp.tool_calls
        ],
    }


def run_tool_loop(
    message: str,
    max_rounds: int = MAX_ROUNDS,
    chat: Callable[..., LLMResult] | None = None,
) -> dict[str, Any]:
    """执行工具循环。

    返回 {answer, tool_calls, rounds, stopped_by}：
      stopped_by = "final_answer" 说明模型自己收口了
      stopped_by = "max_rounds"   说明轮数用完，强制收口
    """
    # 允许注入假模型：离线测试不需要花钱，也不用等网络。
    chat = chat or get_llm_service().chat

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": message},
    ]
    trace: list[dict[str, Any]] = []

    for round_no in range(1, max_rounds + 1):
        resp = chat(messages, temperature=0.0, tools=TOOL_SCHEMAS)

        if not resp.tool_calls:
            return {
                "answer": resp.content,
                "tool_calls": trace,
                "rounds": round_no,
                "stopped_by": "final_answer",
            }

        messages.append(_assistant_tool_message(resp))
        for call in resp.tool_calls:
            result = dispatch(call.name, call.arguments)
            trace.append(
                {"name": call.name, "arguments": call.arguments, "result": result}
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    return {
        "answer": "这个请求需要多步操作，我先帮你转人工处理。",
        "tool_calls": trace,
        "rounds": max_rounds,
        "stopped_by": "max_rounds",
    }
