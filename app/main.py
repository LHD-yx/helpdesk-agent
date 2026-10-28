"""FastAPI 入口。

D1 的 /health 只做 liveness：不调 LLM、不查库，毫秒级返回。
真正探"凭证是否有效"的是 /health?deep=1（下一步加）——
凭证有效性是外部事实，本地读配置文件是看不出来的。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Query

from app.config import BASE_DIR, get_settings
from app.llm import get_llm_service
from app.llm.base import LLMRequestError, LLMUnavailableError
from app.schemas import HealthResponse

app = FastAPI(title="HelpDesk Agent", version="0.1.0")

DB_PATH = BASE_DIR / "data" / "helpdesk.db"


def _probe_llm() -> float:
    """发一次最小请求探凭证与模型可用性，返回耗时毫秒。

    max_tokens=1 是关键：既验证了鉴权和模型名，又把成本压到最低。
    失败时不在这里吞异常，交给调用方按错误类型决定 HTTP 状态码。
    """
    started = time.perf_counter()
    get_llm_service().chat(
        [{"role": "user", "content": "ping"}],
        temperature=0.0,
        max_tokens=1,
    )
    return (time.perf_counter() - started) * 1000


@app.get("/health", response_model=HealthResponse)
def health(
    deep: bool = Query(False, description="true 时真发一次最小请求，探凭证与模型可用性"),
) -> HealthResponse:
    """liveness 默认不联网；deep=1 时做 readiness。"""
    settings = get_settings()
    db_ready = DB_PATH.exists()

    llm_ready: bool | None = None
    llm_latency_ms: float | None = None

    if deep:
        if not db_ready:
            # 依赖不全时不必再花钱调模型
            raise HTTPException(status_code=503, detail={"status": "unavailable", "reason": "db_missing"})
        try:
            llm_latency_ms = _probe_llm()
            llm_ready = True
        except LLMRequestError as exc:
            # 配置/参数问题：换供应商也救不了，要人改配置
            raise HTTPException(
                status_code=503,
                detail={"status": "unavailable", "reason": "llm_config", "error": str(exc)[:200]},
            ) from exc
        except LLMUnavailableError as exc:
            # 服务临时不可用：主备都挂了
            raise HTTPException(
                status_code=503,
                detail={"status": "unavailable", "reason": "llm_unavailable", "error": str(exc)[:200]},
            ) from exc

    return HealthResponse(
        status="ok" if db_ready else "degraded",
        provider=settings.llm_provider,
        model=settings.resolved_model,
        db_ready=db_ready,
        llm_ready=llm_ready,
        llm_latency_ms=llm_latency_ms,
    )
