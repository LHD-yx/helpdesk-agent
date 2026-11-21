"""端到端冒烟：建索引 → 检索 → 政策分支 → 完整响应。

四条验收：
  1. 报销标准 → 含 450，引用 P001
  2. 年假     → 含 5 天，引用 P002
  3. 投诉     → handoff，不检索
  4. 食堂     → 无依据拒答，不编引用

用法（项目根目录）：
    python scripts\smoke_rag.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.orchestrator import handle  # noqa: E402
from app.rag.embedding import embed_one  # noqa: E402
from app.rag.indexer import build_index  # noqa: E402
from app.rag.vector_store import count, query  # noqa: E402

RECALL_CASES = [
    ("出差住宿能报多少钱", "P001", "450"),
    ("年假有几天", "P002", "5 天"),
]

# (问题, 期望 intent, 必须出现的内容, 期望引用政策；None 表示必须没有引用)
E2E_CASES = [
    ("报销标准是多少", "policy_qa", "450", "P001"),
    ("年假有几天", "policy_qa", "5 天", "P002"),
    ("我要投诉", "handoff", None, None),
    ("食堂几点开饭", "policy_qa", None, None),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")

    started = time.perf_counter()
    n = build_index()
    print(f"索引条数: {n}（当前集合: {count()}）  用时 {time.perf_counter()-started:.1f}s")

    ok = 0
    for question, expect_policy, expect_text in RECALL_CASES:
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

    print(f"\n检索命中 {ok}/{len(RECALL_CASES)}")

    print("\n=== 端到端（经过 orchestrator）===")
    e2e = 0
    for question, want_intent, want_text, want_policy in E2E_CASES:
        resp = handle(question, session_id="smoke")
        cites = [c.policy_id for c in resp.citations]
        checks = [
            resp.intent.value == want_intent,
            (want_text in resp.answer) if want_text else True,
            (want_policy in cites) if want_policy else (cites == []),
        ]
        hit = all(checks)
        e2e += hit
        print(f"[{'OK' if hit else 'XX'}] {question}")
        print(f"     intent={resp.intent.value}  cites={cites or '无'}")
        print(f"     answer={resp.answer[:70]}")

    print(f"\n端到端命中 {e2e}/{len(E2E_CASES)}")
    return 0 if (ok == len(RECALL_CASES) and e2e == len(E2E_CASES)) else 1


if __name__ == "__main__":
    raise SystemExit(main())
