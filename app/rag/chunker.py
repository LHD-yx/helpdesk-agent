"""政策文档切片器。

按 Markdown 标题切，`##` 成节，`###` 下面各自成块。两个硬约束：
表格整块保留（"450 元/晚"不能和"普通员工"分开），
每块正文前拼上标题路径，块里没有标题也不会丢上下文。

最早按固定长度硬切，价格表被劈成两半，检索能命中，答案却对不上号。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import BASE_DIR
from app.db.seed import connect

MAX_CHARS = 600          # 目标单块长度
HARD_MAX_CHARS = 800     # 保险上限：任何块都不许超过
OVERLAP_CHARS = 80       # 超长段落切开时的重叠

POLICY_DIR = BASE_DIR / "data" / "policies"


@dataclass(frozen=True)
class Chunk:
    """一个可入库的片段。text 是最终拿去向量化的内容。"""

    text: str
    body: str
    metadata: dict[str, Any]


def split_sections(markdown: str) -> list[tuple[tuple[str, ...], str]]:
    """把 md 拆成 (标题路径, 正文) 列表。

    `###` 会开新节，所以「常见问题」下的每条问答都独立成块。
    """
    sections: list[tuple[tuple[str, ...], str]] = []
    h1 = h2 = h3 = None
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body and h1:
            sections.append((tuple(x for x in (h1, h2, h3) if x), body))

    for line in markdown.splitlines():
        if line.startswith("### "):
            flush()
            buf = []
            h3 = line[4:].strip()
        elif line.startswith("## "):
            flush()
            buf = []
            h2 = line[3:].strip()
            h3 = None
        elif line.startswith("# "):
            flush()
            buf = []
            h1 = line[2:].strip()
            h2 = h3 = None
        else:
            buf.append(line)

    flush()
    return sections


def _is_table(block: str) -> bool:
    return block.lstrip().startswith("|")


def split_long(text: str, max_chars: int = MAX_CHARS) -> list[str]:
    """超长 section 按空行切段打包；表格整块进同一个 chunk。"""
    # 整节放得下就整节保留：段落 + 表格 + 补充说明待在一起，语义最完整。
    if len(text) <= max_chars:
        return [text]

    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    if not blocks:
        return []

    chunks: list[str] = []
    current = ""

    for block in blocks:
        # 表格永远不拆：能塞就塞，塞不下就让它单独成块（哪怕超长）。
        if _is_table(block):
            if current:
                chunks.append(current)
                current = ""
            chunks.append(block)
            continue

        if current and len(current) + 2 + len(block) > max_chars:
            chunks.append(current)
            # 上一块以表格结尾时不带 overlap，避免把表头/表体重复进来。
            tail = "" if _is_table(current) else current[-OVERLAP_CHARS:]
            current = f"{tail}\n\n{block}" if tail else block
        else:
            current = f"{current}\n\n{block}" if current else block

    if current:
        chunks.append(current)
    return chunks


def build_chunks(policy: dict[str, Any], markdown: str) -> list[Chunk]:
    """把一份政策拆成带元数据的 chunk。"""
    chunks: list[Chunk] = []
    for path, body in split_sections(markdown):
        for piece in split_long(body):
            prefix = " > ".join(path)
            chunks.append(
                Chunk(
                    text=f"{prefix}\n\n{piece}",
                    body=piece,
                    metadata={
                        "policy_id": policy["policy_id"],
                        "title": policy["title"],
                        "section": " > ".join(path[1:]) or path[0],
                        "source_file": policy["source_file"],
                        "effective_date": policy["effective_date"],
                        "chunk_index": len(chunks),
                    },
                )
            )
    return chunks


def load_all_chunks() -> list[Chunk]:
    """读数据库里的政策清单 → 读原文 → 切片。"""
    conn = connect()
    try:
        rows = [
            dict(r)
            for r in conn.execute(
                """SELECT policy_id, title, effective_date, source_file
                     FROM policies ORDER BY policy_id"""
            )
        ]
    finally:
        conn.close()

    all_chunks: list[Chunk] = []
    for policy in rows:
        path = POLICY_DIR / policy["source_file"]
        markdown = path.read_text(encoding="utf-8")
        all_chunks.extend(build_chunks(policy, markdown))
    return all_chunks
