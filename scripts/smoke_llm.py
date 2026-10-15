"""Day1 冒烟脚本：环境自检 → 主调用 → 降级演练 → 不降级演练。

用法：
    python scripts/smoke_llm.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

# 让 scripts/ 下的脚本能找到项目根的 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm import LLMService, get_llm_service  # noqa: E402
from app.llm.base import LLMRequestError  # noqa: E402
from app.llm.factory import build_fallback  # noqa: E402
from app.llm.openai_compat import OpenAICompatProvider  # noqa: E402

ASK = [
    {"role": "system", "content": "你是企业内部服务台的助手，回答要简短。"},
    {"role": "user", "content": "用一句话说明什么是企业服务台。"},
]


def step_env_and_config() -> bool:
    settings = get_settings()

    print(f"[1/5] Python {sys.version.split()[0]}")
    print(f"      python   = {sys.executable}")
    # Day1 专用护栏：防止 conda 环境没激活时跑错解释器。
    # Day10 工程化时如果觉得吵，可以删掉。
    if "\\envs\\helpdesk\\" not in sys.executable.lower():
        print("      [!] 当前不在 helpdesk 环境里，请先 conda activate helpdesk")

    print("[2/5] 配置加载完成")
    print(f"      provider  = {settings.llm_provider}")
    print(f"      base_url  = {settings.resolved_base_url}")
    print(f"      model     = {settings.resolved_model}")
    print(f"      api_key   = {settings.masked_key}")
    print(f"      fallback  = {settings.llm_fallback_provider or '(未配置)'}")

    if not settings.llm_api_key:
        print("")
        print("[!] LLM_API_KEY 为空。请先执行：")
        print("      Copy-Item .env.example .env")
        print("      然后编辑 .env 填入你的 key")
        return False
    return True


def step_primary_call() -> None:
    print("[3/5] 主 provider 调用 ...")
    result = get_llm_service().chat(ASK)
    print("-" * 60)
    print("回复：", result.content)
    print("-" * 60)
    print(f"served_by : {result.served_by}     degraded: {result.degraded}")
    print(f"耗时      : {result.latency_ms:.0f} ms")
    print(
        f"token     : 输入 {result.prompt_tokens}"
        f" / 输出 {result.completion_tokens}"
        f" / 合计 {result.total_tokens}"
    )


def step_fallback_drill() -> None:
    """可降级错误：服务根本连不上 → 应该自动切备用。"""
    print("")
    print("[4/5] 降级演练（可降级错误）：主 provider 指向一个连不上的地址")

    fallback = build_fallback()
    if fallback is None:
        print("      跳过：.env 里还没配 LLM_FALLBACK_PROVIDER / LLM_FALLBACK_API_KEY")
        return

    # 127.0.0.1:9 是本机一个没有服务监听的端口，连接会被立刻拒绝，
    # 触发 APIConnectionError → 属于可降级错误。
    # 用本机端口而不是乱写的域名，是为了"快速失败"，不用等 DNS 超时。
    unreachable = OpenAICompatProvider(
        name="unreachable-demo",
        api_key="sk-whatever",
        base_url="http://127.0.0.1:9/v1",
        model="whatever",
        timeout=5.0,
        max_retries=0,
    )

    result = LLMService(primary=unreachable, fallback=fallback).chat(ASK)
    print(f"      确实降级了 → served_by={result.served_by}  degraded={result.degraded}")
    print(f"      备用 provider 的回复：{result.content}")


def step_no_degrade_drill() -> None:
    """不可降级错误：请求被拒绝 → 必须直接抛，不许切备用。

    这是本次修改前会出问题的那条路径：以前它会被降级吞掉，
    返回一个看起来正常的答案，把配置错误完全掩盖。
    """
    print("")
    print("[5/5] 不降级演练（不可降级错误）：用真 key 打一个不存在的模型名")

    fallback = build_fallback()
    if fallback is None:
        print("      跳过：没配备用 provider，就没法演示「本可以降级但没有降」")
        return

    settings = get_settings()
    bogus = OpenAICompatProvider(
        name="bogus-model-demo",
        api_key=settings.llm_api_key,
        base_url=settings.resolved_base_url,
        model="no-such-model-xyz",
        timeout=15.0,
        max_retries=0,
    )

    service = LLMService(primary=bogus, fallback=fallback)
    try:
        service.chat(ASK)
    except LLMRequestError as exc:
        print("      符合预期：请求被拒绝，没有触发降级，直接抛了出来")
        print(f"      错误摘要：{str(exc)[:160]}")
    else:
        print("      [!] 不该走到这里——说明降级又把请求错误吞掉了，检查错误分类")


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    # logging 默认写到 stderr，只修 stdout 的话日志里的中文会乱码
    # （实测：WARNING 行里 provider 名字全变成 ??）。两个流都要修。
    sys.stderr.reconfigure(encoding="utf-8")
    # 让降级时的 logger.warning 能直接打在屏幕上
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    try:
        ok = step_env_and_config()
    except ValueError as exc:
        # 配置错误属于「使用者配错了」，不是程序 bug：给一句人话就够了。
        print(f"配置错误：{exc}")
        return 1

    if not ok:
        return 1

    try:
        step_primary_call()
        step_fallback_drill()
        step_no_degrade_drill()
    except LLMRequestError as exc:
        # 请求被拒绝同样属于「配错了」，而且要明确告诉使用者：它没有触发降级
        print("")
        print(f"请求被拒绝（配置或参数问题，已确认不触发降级）：{exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
