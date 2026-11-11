"""检索层：向量查询 → 阈值过滤 → 排序 → 截断 → 引用。

MIN_SCORE 不是拍脑袋定的：2026-11-11 用真实语料实测，
相关问题 top1 在 0.646–0.715，不相关问题最高 0.534，取 0.55 落在间隙里。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from app.rag.embedding import embed_one
from app.rag.vector_store import query

MIN_SCORE = 0.55
MAX_KEPT = 4
TOP_K = 6  # 先多召回，再过滤：召回少了就没得筛


@dataclass(frozen=True)
class Hit:
    text: str
    metadata: dict[str, Any]
    score: float


def select_hits(
    hits: list[Hit],
    min_score: float = MIN_SCORE,
    max_kept: int = MAX_KEPT,
) -> list[Hit]:
    """只留够像的，按分数从高到低，最多留 max_kept 条。

    自己排序而不是假设调用方已排好：上层换个数据源时不会静默出错。
    """
    kept = [h for h in hits if h.score >= min_score]
    kept.sort(key=lambda h: h.score, reverse=True)
    return kept[:max_kept]


def content_hash(chunks: list[Any]) -> str:
    """把切片内容压成指纹，用来判断索引是否过期。"""
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()


def index_is_stale(chunks: list[Any], manifest: dict[str, Any] | None) -> bool:
    """只比条数会漏掉「内容变了但条数没变」——必须比内容指纹。"""
    if manifest is None:
        return True
    return content_hash(chunks) != manifest.get("hash")


def retrieve(
    question: str,
    top_k: int = TOP_K,
    min_score: float = MIN_SCORE,
) -> list[Hit]:
    raw = query(embed_one(question), top_k=top_k)
    hits = [
        Hit(text=r["text"], metadata=r["metadata"], score=float(r["score"]))
        for r in raw
    ]
    return select_hits(hits, min_score=min_score)


def build_citations(hits: list[Hit]) -> list[dict[str, Any]]:
    """引用来自检索结果，不来自模型记忆。"""
    return [
        {
            "policy_id": h.metadata["policy_id"],
            "title": h.metadata["title"],
            "section": h.metadata["section"],
            "source_file": h.metadata["source_file"],
            "snippet": h.text.split("\n\n", 1)[-1][:120],
            "score": round(h.score, 3),
        }
        for h in hits
    ]
