"""LLM 抽象层：定义「一个模型服务」在本项目里长什么样。

两个设计要点，也是面试可以讲的点：

1. 业务代码只认识 LLMResult / LLMProvider / LLMUnavailableError，
   不认识 openai SDK 的任何类型。以后换供应商、加本地模型，
   业务代码一行都不用改。
2. 把「哪些错误可以降级」收敛成两个自定义异常
   （可降级 / 不可降级），避免业务层到处写 except openai.APIError。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class LLMError(RuntimeError):
    """LLM 层所有错误的基类。业务只想统一兜底时 catch 这一个就够。"""


class LLMUnavailableError(LLMError):
    """服务不可用：超时、连不上、429 限流、5xx。

    特征：换个地方可能就成功 → 允许降级到备用 provider。
    """


class LLMRequestError(LLMError):
    """请求本身被拒绝：400 参数/模型名写错、401 key 无效、403 权限不足、404 不存在。

    特征：换哪个供应商都一样失败，而且通常是我自己的配置或代码有问题。
    如果把它当成服务故障去降级，会用一个「成功」的备用响应把真实错误盖住——
    这是实测踩出来的坑：模型名写成「哈哈」，被 400 拒绝后系统默默切到备用
    provider，返回了一个看起来完全正常的答案，故障被完全掩盖。
    所以它绝不触发降级，直接往上抛。
    """


@dataclass
class ToolCall:
    """模型要求调用某个工具的请求。arguments 保持原始 JSON 字符串。"""

    id: str
    name: str
    arguments: str


@dataclass
class LLMResult:
    """一次模型调用的统一返回结构。业务代码只依赖这个。"""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    finish_reason: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: float = 0.0
    served_by: str = ""      # 实际提供服务的 provider 名（降级后会变）
    degraded: bool = False   # 本次是否发生了降级

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class LLMProvider(Protocol):
    """一个 provider 必须能做的一件事：发一轮对话。

    Protocol 只做类型提示、不强制继承（鸭子类型）。
    以后要接 Ollama 或自研推理服务，只要实现同样的 chat() 就行。
    """

    name: str

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> LLMResult: ...
