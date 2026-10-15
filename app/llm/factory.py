"""provider 工厂 + 降级编排。

- build_provider / build_primary / build_fallback：把配置翻译成可用的 provider 对象
- LLMService：对外只暴露一个 chat()，内部负责「主挂 → 切备用」
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import get_settings, preset_for
from app.llm.base import LLMProvider, LLMResult, LLMUnavailableError
from app.llm.openai_compat import OpenAICompatProvider

logger = logging.getLogger(__name__)


def build_provider(
    name: str,
    api_key: str,
    *,
    base_url: str = "",
    model: str = "",
) -> OpenAICompatProvider:
    """按供应商名 + key 造一个 provider。base_url / model 留空则用预设。"""
    settings = get_settings()
    preset = preset_for(name)
    return OpenAICompatProvider(
        name=name,
        api_key=api_key,
        base_url=base_url or preset["base_url"],
        model=model or preset["model"],
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
    )


def build_primary() -> OpenAICompatProvider:
    settings = get_settings()
    return build_provider(
        settings.llm_provider,
        settings.llm_api_key,
        base_url=settings.llm_base_url,
        model=settings.llm_model,
    )


def build_fallback() -> OpenAICompatProvider | None:
    """没配备用 provider 就返回 None，降级逻辑自动关闭。"""
    settings = get_settings()
    if not settings.has_fallback:
        return None
    return build_provider(settings.llm_fallback_provider, settings.llm_fallback_api_key)


class LLMService:
    """对业务层只暴露 chat()。降级、标记、日志都在这里收口。"""

    def __init__(self, primary: LLMProvider, fallback: LLMProvider | None = None) -> None:
        self.primary = primary
        self.fallback = fallback

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult:
        try:
            result = self.primary.chat(
                messages,
                temperature=temperature,
                tools=tools,
                response_format=response_format,
            )
            result.served_by = self.primary.name
            return result
        except LLMUnavailableError as exc:
            if self.fallback is None:
                raise
            logger.warning(
                "主 provider(%s) 不可用，降级到备用(%s)：%s",
                self.primary.name,
                self.fallback.name,
                exc,
            )
            try:
                result = self.fallback.chat(
                    messages,
                    temperature=temperature,
                    tools=tools,
                    response_format=response_format,
                )
            except LLMUnavailableError as fallback_exc:
                # 主备都挂了：把两条路的原因都写进报错里。
                # 只报备用那一条的话，排查时你只知道"备用失败"，
                # 却不知道起因是"主先失败"——而主失败往往才是根因。
                raise LLMUnavailableError(
                    f"主备均不可用。主({self.primary.name})：{exc}"
                    f" | 备({self.fallback.name})：{fallback_exc}"
                ) from fallback_exc
            # 备用抛 LLMRequestError 则原样穿透：
            # 那说明是配置/参数问题，已经不是"服务不可用"的性质了。
            result.served_by = self.fallback.name
            result.degraded = True
            return result
