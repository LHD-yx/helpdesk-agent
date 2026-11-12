"""跑单条评测用例：python scripts\run_case.py E06

为什么单独写这个脚本，而不是在命令行里 `| python -`：
  Windows PowerShell 5.1 的 $OutputEncoding 默认是 us-ascii，
  管道把中文送进 Python 时会变成问号，模型收到乱码就会回"内容无法识别"。
  从 UTF-8 文件读取，可以彻底绕开这个问题。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.agent.orchestrator import handle  # noqa: E402

CASES = ROOT / "evals" / "testset.jsonl"


def load_case(case_id: str) -> dict:
    for line in CASES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] == case_id:
            return row
    raise SystemExit(f"评测集里没有 {case_id}")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    case_id = sys.argv[1] if len(sys.argv) > 1 else "E06"
    case = load_case(case_id)

    print(f"[{case_id}] {case['message']}")
    print(
        f"期望: intent={case['expected_intent']} "
        f"policy={case['expected_policy']} no_basis={case['expect_no_basis']}"
    )

    resp = handle(case["message"], session_id=f"single-{case_id}")

    cites = [f"{c.policy_id} / {c.section}" for c in resp.citations]
    ok_intent = resp.intent.value == case["expected_intent"]
    ok_policy = (
        case["expected_policy"] in [c.policy_id for c in resp.citations]
        if case["expected_policy"]
        else (cites == [])
    )

    print(f"实际: intent={resp.intent.value} confidence={resp.confidence:.2f}")
    print(f"      request_id={resp.request_id} served_by={resp.served_by or '-'} "
          f"degraded={resp.degraded}")
    print(f"      fallback={resp.fallback} reason={resp.fallback_reason or '-'}")
    print(f"引用: {cites or '无'}")
    print(f"答案: {resp.answer}")
    print(f"判定: 意图 {'OK' if ok_intent else 'XX'} | 引用 {'OK' if ok_policy else 'XX'}")
    return 0 if (ok_intent and ok_policy) else 1


if __name__ == "__main__":
    raise SystemExit(main())
