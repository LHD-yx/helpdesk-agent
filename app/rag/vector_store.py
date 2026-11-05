"""Chroma 持久化封装。

只暴露四个动作：数一下、清空重建、写入、查询。
业务层不需要知道 Chroma 的任何细节。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import chromadb

from app.config import BASE_DIR
from app.rag.chunker import Chunk

CHROMA_DIR = BASE_DIR / "data" / "chroma"
COLLECTION_NAME = "policies"


@lru_cache(maxsize=1)
def _client() -> Any:
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(CHROMA_DIR))


def get_collection() -> Any:
    """拿到（或创建）政策集合。cosine 距离与 bge-m3 的用法一致。"""
    return _client().get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def reset_collection() -> Any:
    """删掉重建。只在重建索引时调用。"""
    try:
        _client().delete_collection(COLLECTION_NAME)
    except Exception:  # 集合不存在时忽略
        pass
    return get_collection()


def count() -> int:
    return get_collection().count()


def add_chunks(chunks: list[Chunk], vectors: list[list[float]]) -> None:
    if len(chunks) != len(vectors):
        raise ValueError(f"chunk 数 {len(chunks)} 与向量数 {len(vectors)} 不一致")
    get_collection().add(
        ids=[f"{c.metadata['policy_id']}-{c.metadata['chunk_index']}" for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[c.metadata for c in chunks],
        embeddings=vectors,
    )


def query(vector: list[float], top_k: int = 4) -> list[dict[str, Any]]:
    """返回 top_k 命中，score = 1 - cosine_distance，越大越像。"""
    collection = get_collection()
    n = min(top_k, collection.count())
    if n == 0:
        return []

    result = collection.query(
        query_embeddings=[vector],
        n_results=n,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict[str, Any]] = []
    for text, meta, dist in zip(
        result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append({"text": text, "metadata": meta, "score": 1.0 - float(dist)})
    return hits
