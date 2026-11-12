"""B4 离线检查：只验证过滤逻辑，不调模型、不花钱。

用法（项目根目录）：
    python scripts\check_retriever.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.retriever import (  # noqa: E402
    Hit,
    content_hash,
    index_is_stale,
    select_hits,
    split_question,
)


def h(score: float, pid: str = "P001") -> Hit:
    return Hit(text=f"chunk-{score}", metadata={"policy_id": pid}, score=score)


@dataclass
class FakeChunk:
    text: str


def check_empty() -> None:
    assert select_hits([]) == [], "空输入应该返回空列表"


def check_threshold() -> None:
    kept = select_hits([h(0.82), h(0.61), h(0.31)], min_score=0.55)
    scores = [x.score for x in kept]
    assert scores == [0.82, 0.61], f"低分应被过滤，实际保留 {scores}"


def check_order() -> None:
    kept = select_hits([h(0.62), h(0.91), h(0.75)], min_score=0.55)
    scores = [x.score for x in kept]
    assert scores == [0.91, 0.75, 0.62], f"应按分数降序，实际 {scores}"


def check_limit() -> None:
    kept = select_hits(
        [h(0.9), h(0.8), h(0.7), h(0.6), h(0.58), h(0.4)],
        min_score=0.55,
        max_kept=4,
    )
    assert len(kept) == 4, f"最多保留 4 条，实际 {len(kept)}"
    assert kept[0].score == 0.9, "保留的应该是最高的 4 条"


def check_staleness() -> None:
    chunks = [FakeChunk("红烧牛肉面"), FakeChunk("清蒸鲈鱼")]
    manifest = {"count": len(chunks), "hash": content_hash(chunks)}
    assert not index_is_stale(chunks, manifest), "内容没变时不该判定为过期"

    # 改了一句话，但块数仍然是 2
    changed = [FakeChunk("红烧牛肉面（已下架）"), FakeChunk("清蒸鲈鱼")]
    assert index_is_stale(changed, manifest), "内容变了但块数没变，也应判定为过期"


def check_split_compound() -> None:
    parts = split_question("申请生产数据库权限需要谁审批，权限有效多久？")
    assert parts == ["申请生产数据库权限需要谁审批", "权限有效多久"], (
        f"复合问句应拆成两段，实际 {parts}"
    )


def check_split_drops_short() -> None:
    assert split_question("报销怎么走？嗯") == ["报销怎么走"], "过短子句应被丢弃"
    assert split_question("年假有几天") == ["年假有几天"], "无标点时应原样返回"


CHECKS = [
    ("空输入返回空", check_empty),
    ("低分被过滤", check_threshold),
    ("结果按分数降序", check_order),
    ("最多保留 4 条", check_limit),
    ("内容变了但条数没变 → 索引过期", check_staleness),
    ("复合问句拆分", check_split_compound),
    ("短子句丢弃 / 无标点原样", check_split_drops_short),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    passed = 0
    for name, fn in CHECKS:
        try:
            fn()
        except AssertionError as exc:
            print(f"[XX] {name} —— {exc}")
        except Exception as exc:
            print(f"[XX] {name} —— 抛出了未处理的 {type(exc).__name__}: {exc}")
        else:
            print(f"[OK] {name}")
            passed += 1

    print(f"\n通过 {passed}/{len(CHECKS)}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
