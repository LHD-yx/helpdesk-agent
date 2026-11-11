"""政策分支：检索 → 拼上下文 → 生成 → 附引用。

三条原则：
1. 只依据检索到的资料回答，资料不够就说没有依据。
2. 引用由代码拼，模型不许自己编来源。
3. 检索不到就转人工，不要硬答。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.llm import get_llm_service
from app.rag.retriever import Hit, build_citations, retrieve

NO_BASIS_ANSWER = "公司政策里没有找到相关规定，我把这个问题转给人工同事处理。"

SYSTEM_PROMPT = """你是企业政策助手。严格遵守：
1. 只能依据【资料】回答，不得使用资料之外的知识。
2. 资料不足时直接说"公司政策里没有找到相关规定"，不要猜测、不要补充常识。
3. 回答简洁，并在关键结论后标注来源编号，例如 [P001]。
"""


@dataclass(frozen=True)
class PolicyAnswer:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    top_score: float = 0.0
    fallback: bool = False
    fallback_reason: str = ""


def _context(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{h.metadata['policy_id']}] {h.text}" for h in hits)


def answer(question: str) -> PolicyAnswer:
    hits = retrieve(question)
    if not hits:
        return PolicyAnswer(
            answer=NO_BASIS_ANSWER,
            citations=[],
            top_score=0.0,
            fallback=True,
            fallback_reason="no_policy_hit",
        )

    resp = get_llm_service().chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"【资料】\n{_context(hits)}\n\n【问题】{question}",
            },
        ],
        temperature=0.1,
    )
    return PolicyAnswer(
        answer=resp.content.strip(),
        citations=build_citations(hits),
        top_score=hits[0].score,
    )
