"""LLM 层对外入口。

业务代码只写 `from app.llm import get_llm_service`，
不要直接 import openai_compat 里的类。
"""

from functools import lru_cache

from app.llm.base import (
    LLMError,
    LLMProvider,
    LLMRequestError,
    LLMResult,
    LLMUnavailableError,
    ToolCall,
)
from app.llm.factory import LLMService, build_fallback, build_primary

__all__ = [
    "LLMError",
    "LLMProvider",
    "LLMRequestError",
    "LLMResult",
    "LLMUnavailableError",
    "ToolCall",
    "LLMService",
    "get_llm_service",
]


@lru_cache(maxsize=1)
def get_llm_service() -> LLMService:
    """单例。整个进程共用一套 provider，避免每次请求都新建 client。"""
    return LLMService(primary=build_primary(), fallback=build_fallback())
