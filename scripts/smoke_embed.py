"""B1 冒烟：验证 embedding 能出 1024 维向量，且语义上分得开。

用法（项目根目录）：
    python scripts\smoke_embed.py
"""

from __future__ import annotations

import math
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.embedding import EmbeddingError, embed_texts  # noqa: E402

QUERY = "出差住宿能报销多少钱"

DOC_A = "差旅报销标准：一线城市普通员工住宿上限 450 元/晚，出差结束后 15 个工作日内提交。"
DOC_B = "年假与调休规则：入职满一年享有 5 天年假，调休当年有效。"


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    started = time.perf_counter()
    try:
        vectors = embed_texts([QUERY, DOC_A, DOC_B])
    except EmbeddingError as exc:
        # 偶发的网络/限流失败也要说清楚，别让使用者对着空输出猜。
        print(f"[!!] Embedding 调用失败：{exc}")
        print("     排查：网络是否可达 api.siliconflow.cn；key 是否还有额度；稍后重试")
        return 1
    elapsed = (time.perf_counter() - started) * 1000

    q, a, b = vectors
    print(f"文本数    : {len(vectors)}")
    print(f"维度      : {len(q)}（期望 1024）")
    print(f"耗时      : {elapsed:.0f} ms")
    print(f"相似度 A  : {cosine(q, a):.4f}   ← 差旅报销")
    print(f"相似度 B  : {cosine(q, b):.4f}   ← 年假规则")

    if len(q) != 1024:
        print("\n[!!] 维度不对，检查 EMBEDDING_MODEL 配置")
        return 1
    if cosine(q, a) <= cosine(q, b):
        print("\n[!!] 语义没分开：报销问题和差旅文档的相似度应该更高")
        return 1

    print("\n[OK] Embedding 可用，且语义区分正常")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
