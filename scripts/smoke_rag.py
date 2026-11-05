"""B3 冒烟：建索引 → 检索。只验证能不能召回对的政策，不生成答案。

用法（项目根目录）：
    python scripts\smoke_rag.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.embedding import embed_one  # noqa: E402
from app.rag.indexer import build_index  # noqa: E402
from app.rag.vector_store import count, query  # noqa: E402

CASES = [
    ("出差住宿能报多少钱", "P001", "450"),
    ("年假有几天", "P002", "5 天"),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    started = time.perf_counter()
    n = build_index()
    print(f"索引条数: {n}（当前集合: {count()}）  用时 {time.perf_counter()-started:.1f}s")

    ok = 0
    for question, expect_policy, expect_text in CASES:
        hits = query(embed_one(question), top_k=3)
        if not hits:
            print(f"[XX] {question} —— 没有召回任何内容")
            continue

        top = hits[0]
        hit = (
            top["metadata"]["policy_id"] == expect_policy
            and expect_text in top["text"]
        )
        ok += hit
        print(f"\n[{'OK' if hit else 'XX'}] {question}")
        for h in hits:
            print(
                f"    {h['score']:.3f}  {h['metadata']['policy_id']}  "
                f"{h['metadata']['section']}"
            )
        if not hit:
            print(f"    期望 top1 为 {expect_policy} 且包含「{expect_text}」")

    print(f"\n命中 {ok}/{len(CASES)}")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
