"""D3 离线自检：切片部分（B2）。

用法（项目根目录）：
    python scripts\check_rag.py

不调模型、不花钱。B3/B4 会往这里追加检索与引用检查。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.rag.chunker import HARD_MAX_CHARS, load_all_chunks  # noqa: E402

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'[OK]' if ok else '[XX]'} {label}" + (f" — {detail}" if detail else ""))
    if not ok:
        failures.append(label)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    chunks = load_all_chunks()

    print("=" * 62)
    print(f"共切出 {len(chunks)} 个 chunk")
    print("=" * 62)

    check("块数在 20–60 之间", 20 <= len(chunks) <= 60, f"实际 {len(chunks)}")
    check("没有空块", all(c.text.strip() for c in chunks))

    required = {"policy_id", "title", "section", "source_file", "effective_date"}
    missing = [c.metadata for c in chunks if not required <= set(c.metadata)]
    check("元数据齐全", not missing, f"{len(missing)} 块缺字段")

    check(
        "四个政策都覆盖到",
        {c.metadata["policy_id"] for c in chunks} == {"P001", "P002", "P003", "P004"},
    )

    # 首行必须是标题路径。只有一级标题的引言段也合法（如「差旅报销标准」本身）。
    check(
        "每块首行都是标题路径",
        all(
            c.text.split("\n", 1)[0].startswith(c.metadata["title"])
            for c in chunks
        ),
    )

    # 住宿价格表必须完整落在一个块里，否则数字会对错行。
    table_intact = any(
        "普通员工" in c.body and "800 元/晚" in c.body for c in chunks
    )
    check("住宿价格表没被切碎", table_intact)

    too_long = [c for c in chunks if len(c.text) > HARD_MAX_CHARS]
    check("没有超过硬上限的块", not too_long, f"{len(too_long)} 块超长")

    print("-" * 62)
    for c in chunks[:3]:
        head = c.text.split("\n")[0]
        print(f"样例 {c.metadata['policy_id']} #{c.metadata['chunk_index']} "
              f"[{len(c.text)} 字] {head}")

    print("=" * 62)
    if failures:
        print(f"结论：{len(failures)} 项不通过 → {failures}")
        return 1
    print("结论：切片层健康 ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
