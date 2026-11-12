"""离线检查：拒答分级（全拒 / 部分拒 / 幻觉引用），不调模型、不花钱。

用法（项目根目录）：
    python scripts\check_policy.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.agent.policy_qa as pq  # noqa: E402
from app.llm.base import LLMResult  # noqa: E402

HIT = pq.Hit(
    text="五、权限有效期\n所有系统权限的有效期为 90 天。",
    metadata={
        "policy_id": "P004",
        "title": "信息系统账号与权限管理",
        "section": "五、权限有效期",
        "source_file": "P004-it-account.md",
    },
    score=0.75,
)


class FakeLLM:
    """假模型：固定返回一段文本，用来测分支而不烧 token。"""

    def __init__(self, content: str) -> None:
        self._content = content

    def chat(self, *_args, **_kwargs) -> LLMResult:
        return LLMResult(content=self._content, served_by="fake")


def run(answer_text: str):
    pq.retrieve = lambda *_a, **_k: [HIT]
    pq.get_llm_service = lambda: FakeLLM(answer_text)
    return pq.answer("测试问题")


def check_normal() -> None:
    r = run("需要双签 [P004]。")
    assert not r.fallback, "正常回答不该被标成兜底"
    assert [c["policy_id"] for c in r.citations] == ["P004"], "正常回答必须带引用"


def check_full_reject() -> None:
    r = run(pq.NO_BASIS_ANSWER)
    assert r.fallback and r.fallback_reason == "no_policy_basis", r.fallback_reason
    assert r.citations == [], "全拒时必须清空引用"


def check_partial_reject() -> None:
    r = run("生产库权限需要双签 [P004]。\n\n关于有效期，公司政策里没有找到相关规定。")
    assert r.fallback and r.fallback_reason == "partial_no_basis", r.fallback_reason
    assert [c["policy_id"] for c in r.citations] == ["P004"], "部分拒答必须保留已有引用"


def check_hallucinated_citation() -> None:
    # 模型编了一个不存在的政策编号，不能因此认定"已经答了一部分"
    r = run("按 [P999] 规定执行。\n\n关于有效期，公司政策里没有找到相关规定。")
    assert r.fallback and r.fallback_reason == "no_policy_basis", r.fallback_reason
    assert r.citations == [], "幻觉编号不算真实引用"


CHECKS = [
    ("正常回答带引用", check_normal),
    ("全拒清空引用", check_full_reject),
    ("部分拒答保留引用", check_partial_reject),
    ("幻觉政策号不算真实引用", check_hallucinated_citation),
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
            print(f"[XX] {name} —— 未处理的 {type(exc).__name__}: {exc}")
        else:
            print(f"[OK] {name}")
            passed += 1
    print(f"\n通过 {passed}/{len(CHECKS)}")
    return 0 if passed == len(CHECKS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
