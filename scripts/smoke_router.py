"""路由冒烟：6 条边界用例，只打结果，不接 FastAPI。

用法（在项目根目录执行）：
    python scripts\smoke_router.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent.router import classify  # noqa: E402
from app.schemas import Intent  # noqa: E402

CASES: list[tuple[str, Intent]] = [
    ("查工单 T1001", Intent.TICKET_OP),
    ("报销标准是多少", Intent.POLICY_QA),
    ("我要投诉，转人工", Intent.HANDOFF),
    ("帮我看看 T1001 现在怎么样了", Intent.TICKET_OP),
    ("我想申请年假，有什么规定", Intent.POLICY_QA),
    ("今天天气怎么样", Intent.HANDOFF),
    ("我电脑开不了机", Intent.TICKET_OP),
]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    hits = 0
    for i, (message, expected) in enumerate(CASES, 1):
        result = classify(message)
        hit = result.intent is expected
        hits += hit
        print(f"{i}. [{'OK' if hit else 'XX'}] {message}")
        print(
            f"   期望={expected.value:<10}"
            f"实际={result.intent.value:<10}"
            f"置信度={result.confidence:.2f} 理由={result.reason}"
        )
    print(f"\n命中 {hits}/{len(CASES)}（通过线：>= 6）")
    return 0 if hits >= 6 else 1


if __name__ == "__main__":
    raise SystemExit(main())
