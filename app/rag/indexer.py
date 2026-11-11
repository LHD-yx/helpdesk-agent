"""建索引：读政策 → 切片 → 向量化 → 写 Chroma。

索引是「派生数据」：删掉可以重建，所以不进 git。
"""

from __future__ import annotations

import json

from app.config import BASE_DIR
from app.rag.chunker import load_all_chunks
from app.rag.embedding import embed_texts
from app.rag.retriever import content_hash, index_is_stale
from app.rag.vector_store import add_chunks, count, reset_collection

MANIFEST_PATH = BASE_DIR / "data" / "chroma" / "manifest.json"


def _load_manifest() -> dict | None:
    if not MANIFEST_PATH.exists():
        return None
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_manifest(chunks: list) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(
            {"count": len(chunks), "hash": content_hash(chunks)},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def build_index(force: bool = False) -> int:
    """构建政策索引，返回入库条数。

    复用条件有两道：内容指纹没变，且库里的条数对得上。
    只比条数会漏掉「改了一句话但块数没变」的静默过期。
    """
    chunks = load_all_chunks()
    if not force and not index_is_stale(chunks, _load_manifest()) and count() == len(chunks):
        return count()

    vectors = embed_texts([c.text for c in chunks])
    reset_collection()
    add_chunks(chunks, vectors)
    _save_manifest(chunks)
    return count()
