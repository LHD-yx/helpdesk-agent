"""Embedding 客户端：硅基流动 BAAI/bge-m3（1024 维，免费）。

为什么单独一个模块，而不是塞进 app/llm：
  LLM 层抽象的是「生成」，这里抽象的是「向量化」。两者能力不同、失败模式不同。
  混在一起会让 LLMProvider 的协议越来越宽，最后变成什么都干的上帝对象。
"""

from __future__ import annotations

from functools import lru_cache

from openai import OpenAI

from app.config import get_settings


class EmbeddingError(RuntimeError):
    """向量化失败。单独一类，方便上层把它和 LLM 的错误分开处理。"""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    settings = get_settings()
    return OpenAI(
        api_key=settings.resolved_embedding_key,
        base_url=settings.embedding_base_url,
        timeout=30.0,
        max_retries=2,
    )


def embed_texts(texts: list[str], batch_size: int = 16) -> list[list[float]]:
    """把一批文本转成向量。返回顺序与输入一致。"""
    if not texts:
        return []
    if any(not t.strip() for t in texts):
        raise EmbeddingError("待向量化的文本里有空字符串")

    settings = get_settings()
    vectors: list[list[float]] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        try:
            resp = _client().embeddings.create(
                model=settings.embedding_model,
                input=batch,
            )
        except Exception as exc:  # SDK 异常体系之外还有网络层异常，统一收口
            raise EmbeddingError(f"Embedding 请求失败：{exc}") from exc

        ordered = sorted(resp.data, key=lambda d: d.index)
        vectors.extend([d.embedding for d in ordered])

    dims = {len(v) for v in vectors}
    if dims != {settings.embedding_dim}:
        raise EmbeddingError(
            f"向量维度异常：期望 {settings.embedding_dim}，实际 {sorted(dims)}"
        )
    return vectors


def embed_one(text: str) -> list[float]:
    return embed_texts([text])[0]
