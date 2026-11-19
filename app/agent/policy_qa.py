"""政策分支：检索 → 拼上下文 → 生成 → 附引用。

三条原则：
1. 只依据检索到的资料回答，资料不够就说没有依据。
2. 引用由代码拼，模型不许自己编来源。
3. 检索不到就转人工，不要硬答。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.llm import get_llm_service
from app.rag.retriever import Hit, build_citations, retrieve

NO_BASIS_ANSWER = "公司政策里没有找到相关规定，我把这个问题转给人工同事处理。"
NO_BASIS_MARKER = "公司政策里没有找到相关规定"
MIN_SUBSTANTIVE_CHARS = 10

# 模型会改写拒答句（"没有找到育儿假的相关规定"），不能用精确字符串匹配，
# 否则整句都认不出来，全拒会被当成正常回答。
NO_BASIS_PATTERN = re.compile(
    r"(?:公司|企业)(?:的)?政策(?:里|中|上)?(?:没有|未)(?:找到|包含|提及|规定|明确)[^。\n]*"
)

# 只认 [P001] 这种编号，且必须是本次检索真的命中的政策——
# 模型凭空写一个 [P999] 不算"答了一部分"。
CITATION_MARKER = re.compile(r"\[(P\d{3})\]")

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
    served_by: str = ""
    degraded: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0


def _context(hits: list[Hit]) -> str:
    return "\n\n".join(f"[{h.metadata['policy_id']}] {h.text}" for h in hits)


def _has_substantive_content(answer_text: str) -> bool:
    """去掉拒答句、引用标记和标点后，是否还剩实质内容。

    不能只看"有没有 [Pxxx]"：模型会在一块「没找到」的答案后面硬加一个
    真实政策号（实测 E08 把 [P002] 贴在"没有找到育儿假"后面），
    那样"有引用标记 = 部分拒答"的判据就被绕过了。
    """
    residual = NO_BASIS_PATTERN.sub("", answer_text)
    residual = CITATION_MARKER.sub("", residual)
    residual = re.sub(r"[\s，。、；：！？,.!?;:（）()\[\]\"'“”‘’—\-]", "", residual)
    return len(residual) >= MIN_SUBSTANTIVE_CHARS


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
    answer_text = resp.content.strip()
    citations = build_citations(hits)

    # 关键区分：全拒 vs 部分拒。
    # 全拒 = 整条回答没有任何可用依据 → 清空引用。
    # 部分拒 = 答了一部分并标了真实来源，只对另一半说"没找到" → 必须保留引用，
    #          否则用户看到的是"有结论但没出处"，比不答更糟。
    refused = bool(NO_BASIS_PATTERN.search(answer_text))
    cited_ids = set(CITATION_MARKER.findall(answer_text))
    known_ids = {h.metadata["policy_id"] for h in hits}
    has_real_citation = bool(cited_ids & known_ids)

    if refused and not (has_real_citation and _has_substantive_content(answer_text)):
        return PolicyAnswer(
            answer=answer_text,
            citations=[],
            top_score=hits[0].score,
            fallback=True,
            fallback_reason="no_policy_basis",
            served_by=resp.served_by,
            degraded=resp.degraded,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
        )

    if refused:
        return PolicyAnswer(
            answer=answer_text,
            citations=citations,
            top_score=hits[0].score,
            fallback=True,
            fallback_reason="partial_no_basis",
            served_by=resp.served_by,
            degraded=resp.degraded,
            prompt_tokens=resp.prompt_tokens,
            completion_tokens=resp.completion_tokens,
        )

    return PolicyAnswer(
        answer=answer_text,
        citations=citations,
        top_score=hits[0].score,
        served_by=resp.served_by,
        degraded=resp.degraded,
        prompt_tokens=resp.prompt_tokens,
        completion_tokens=resp.completion_tokens,
    )
