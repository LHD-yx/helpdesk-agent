"""OpenAI 兼容协议的 provider 实现。

DeepSeek、硅基流动、通义（兼容模式）、Ollama 都实现了这套协议，
所以一个类就能覆盖四家，差别只在 base_url / model / key。
"""

from __future__ import annotations

import time
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    OpenAIError,
    RateLimitError,
)

from app.llm.base import LLMRequestError, LLMResult, LLMUnavailableError, ToolCall

# 只有这几类错误才允许降级：它们代表「服务侧临时故障，换个地方可能就成功」。
# 其余 OpenAIError（400/401/403/404）都属于「请求被拒绝」，换谁都一样失败，
# 必须直接抛出去，不能让降级用一个「成功」的备用响应把它盖住。
DEGRADABLE_ERRORS = (
    APITimeoutError,       # 超时
    APIConnectionError,    # 连不上 / DNS 失败 / 连接被拒
    RateLimitError,        # 429 限流
    InternalServerError,   # 5xx
)


class OpenAICompatProvider:
    """把 openai SDK 包一层，对外只吐 LLMResult。"""

    def __init__(
        self,
        *,
        name: str,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> None:
        self.name = name
        self.model = model
        self.default_temperature = temperature
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,          # 单次请求超时
            max_retries=max_retries,  # SDK 内置指数退避，覆盖 429 / 5xx / 连接错误
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.default_temperature if temperature is None else temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        if response_format:
            payload["response_format"] = response_format

        started = time.perf_counter()
        try:
            resp = self._client.chat.completions.create(**payload)
        except OpenAIError as exc:
            # 把 SDK 的错误体系翻译成本项目自己的两类错误。
            # 注意：只 catch OpenAIError，不 catch Exception——
            # 我们自己写错的代码（KeyError 之类）应该原样抛出，不该被这里吞掉。
            if isinstance(exc, DEGRADABLE_ERRORS):
                raise LLMUnavailableError(f"[{self.name}] 服务不可用: {exc}") from exc
            # 请求被拒绝（400/401/403/404）：换备用 provider 也救不了，
            # 而且会用一个「降级成功」把配置错误盖住。
            raise LLMRequestError(f"[{self.name}] 请求被拒绝: {exc}") from exc
        latency_ms = (time.perf_counter() - started) * 1000

        message = resp.choices[0].message
        tool_calls: list[ToolCall] = []
        for call in message.tool_calls or []:
            tool_calls.append(
                ToolCall(
                    id=call.id,
                    name=call.function.name,
                    # 保持原始 JSON 字符串，不在这里解析：
                    # Day4 会做防御性解析，模型偶尔会吐出非法 JSON。
                    arguments=call.function.arguments or "{}",
                )
            )

        usage = resp.usage
        return LLMResult(
            content=message.content or "",
            tool_calls=tool_calls,
            model=resp.model or self.model,
            finish_reason=resp.choices[0].finish_reason or "",
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
            latency_ms=latency_ms,
        )
