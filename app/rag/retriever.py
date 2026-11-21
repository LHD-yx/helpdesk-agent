"""检索层：向量查询 → 阈值过滤 → 排序 → 截断 → 引用。

MIN_SCORE 是实测出来的：2026-11-11 用真实语料跑，相关问题 top1 在 0.646–0.715，
不相关问题最高 0.534，0.55 正好落在间隙里。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from app.rag.embedding import embed_one
from app.rag.vector_store import query

MIN_SCORE = 0.55
MAX_KEPT = 4
TOP_K = 6  # 先多召回，再过滤：召回少了就没得筛

# 复合问句拆分：「申请生产数据库权限需要谁审批，权限有效多久？」
# 整体做 embedding 时，向量会被两个诉求平均掉，"权限有效期"章节进不了 top-k。
SPLIT_PATTERN = re.compile(r"[，。；？！,;?!]+")
MIN_SUBQUERY_LEN = 4   # 太短的子句（如"在吗"）单独检索只会引入噪声
MAX_SUBQUERIES = 3     # 一句话最多拆三段，避免 embedding 调用次数失控


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


def split_question(question: str) -> list[str]:
    """把复合问句拆成子问题；没有标点时原样返回。"""
    parts = [p.strip() for p in SPLIT_PATTERN.split(question)]
    parts = [p for p in parts if len(p) >= MIN_SUBQUERY_LEN]
    if not parts:
        stripped = question.strip()
        return [stripped] if stripped else []
    return parts[:MAX_SUBQUERIES]


def retrieve(
    question: str,
    top_k: int = TOP_K,
    min_score: float = MIN_SCORE,
    max_kept: int = MAX_KEPT,
) -> list[Hit]:
    """先拆子问题逐个检索，再按 (policy_id, section) 去重合并。

    同一章节被多个子问题召回时保留高分那一次；合并后整体排序截断，
    所以不会因为多查几次就把无关内容塞进上下文。
    """
    sub_questions = split_question(question)
    if not sub_questions:
        return []

    best: dict[tuple[str, str], Hit] = {}
    for sub in sub_questions:
        for r in query(embed_one(sub), top_k=top_k):
            hit = Hit(
                text=r["text"],
                metadata=r["metadata"],
                score=float(r["score"]),
            )
            key = (hit.metadata["policy_id"], hit.metadata["section"])
            if key not in best or hit.score > best[key].score:
                best[key] = hit

    return select_hits(list(best.values()), min_score=min_score, max_kept=max_kept)


def build_citations(hits: list[Hit]) -> list[dict[str, Any]]:
    """引用来自检索结果，不来自模型记忆。

    用 .get 而不是下标：索引可能是在旧版切片器下建的，元数据字段不一定齐全。
    缺 title/section 不该让整个请求 500；缺 policy_id 则直接丢弃——
    没有政策编号的引用无法溯源，留着只会误导。
    """
    citations: list[dict[str, Any]] = []
    for h in hits:
        meta = h.metadata or {}
        policy_id = meta.get("policy_id")
        if not policy_id:
            continue
        citations.append(
            {
                "policy_id": policy_id,
                "title": meta.get("title", ""),
                "section": meta.get("section", ""),
                "source_file": meta.get("source_file", ""),
                "snippet": h.text.split("\n\n", 1)[-1][:120],
                "score": round(h.score, 3),
            }
        )
    return citations
