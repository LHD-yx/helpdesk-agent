"""D4 fallback 离线检查：不调用模型、不访问 RAG 索引。

验证：
1. ChatResponse 默认不降级；
2. 政策检索为空时产生结构化 fallback；
3. orchestrator 透传 fallback，同时保持 intent 原判；
4. 正常政策结果默认不降级。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agent import orchestrator, policy_qa  # noqa: E402
from app.agent.policy_qa import PolicyAnswer  # noqa: E402
from app.agent.router import IntentResult  # noqa: E402
from app.llm import LLMResult  # noqa: E402
from app.schemas import ChatResponse, Intent  # noqa: E402


def check_response_defaults() -> None:
    response = ChatResponse(
        answer="正常回答",
        intent=Intent.POLICY_QA,
        confidence=0.9,
        session_id="check-fallback",
    )
    assert response.fallback is False
    assert response.fallback_reason == ""
    print("[OK] ChatResponse fallback 默认值为 false / 空字符串")


def check_policy_no_hit() -> None:
    original_retrieve = policy_qa.retrieve
    policy_qa.retrieve = lambda _question: []
    try:
        result = policy_qa.answer("公司有育儿假吗")
    finally:
        policy_qa.retrieve = original_retrieve

    assert result.fallback is True
    assert result.fallback_reason == "no_policy_hit"
    assert result.citations == []
    assert "没有找到相关规定" in result.answer
    print("[OK] 政策无召回产生 fallback=True, reason=no_policy_hit")


def check_orchestrator_passthrough() -> None:
    original_classify = orchestrator.classify
    original_policy_answer = orchestrator.policy_answer
    # 路由已支持 history（多轮记忆），测试桩也要跟着改签名。
    orchestrator.classify = lambda _message, _history=None: IntentResult(
        intent=Intent.POLICY_QA,
        confidence=0.93,
        reason="询问公司政策",
    )
    orchestrator.policy_answer = lambda _message: PolicyAnswer(
        answer="没有依据，已转人工",
        citations=[],
        fallback=True,
        fallback_reason="no_policy_hit",
    )
    try:
        response = orchestrator.handle("公司有育儿假吗", session_id="check-fallback")
    finally:
        orchestrator.classify = original_classify
        orchestrator.policy_answer = original_policy_answer

    assert response.intent is Intent.POLICY_QA
    assert response.fallback is True
    assert response.fallback_reason == "no_policy_hit"
    print("[OK] orchestrator 透传 fallback，intent 保持 policy_qa")


def check_normal_policy_default() -> None:
    result = PolicyAnswer(answer="年假为 5 天")
    assert result.fallback is False
    assert result.fallback_reason == ""
    print("[OK] 正常政策结果默认不标记 fallback")


def check_policy_model_reports_no_basis() -> None:
    class FakeService:
        def chat(self, _messages, **_kwargs):
            return LLMResult(content=policy_qa.NO_BASIS_ANSWER)

    fake_hit = SimpleNamespace(
        metadata={"policy_id": "P002"},
        text="年假天数按司龄计算",
        score=0.636,
    )
    original_retrieve = policy_qa.retrieve
    original_get_service = policy_qa.get_llm_service
    policy_qa.retrieve = lambda _question: [fake_hit]
    policy_qa.get_llm_service = lambda: FakeService()
    try:
        result = policy_qa.answer("员工有育儿假吗")
    finally:
        policy_qa.retrieve = original_retrieve
        policy_qa.get_llm_service = original_get_service

    assert result.fallback is True
    assert result.fallback_reason == "no_policy_basis"
    assert result.citations == []
    print("[OK] 模型明确无依据时清空相似引用并标记 no_policy_basis")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    check_response_defaults()
    check_policy_no_hit()
    check_orchestrator_passthrough()
    check_normal_policy_default()
    check_policy_model_reports_no_basis()
    print("[OK] fallback 收口检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
