"""建索引：读政策 → 切片 → 向量化 → 写 Chroma。

索引是「派生数据」：删掉可以重建，所以不进 git。
"""

from __future__ import annotations

from app.rag.chunker import load_all_chunks
from app.rag.embedding import embed_texts
from app.rag.vector_store import add_chunks, count, reset_collection


def build_index(force: bool = False) -> int:
    """构建政策索引，返回入库条数。

    force=False 时，如果现有条数已经等于切片数，就直接复用，不再花 embedding 调用。
    """
    chunks = load_all_chunks()
    if not force and count() == len(chunks):
        return count()

    vectors = embed_texts([c.text for c in chunks])
    reset_collection()
    add_chunks(chunks, vectors)
    return count()
