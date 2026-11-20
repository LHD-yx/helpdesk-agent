"""FastAPI 入口。

D1 的 /health 只做 liveness：不调 LLM、不查库，毫秒级返回。
真正探"凭证是否有效"的是 /health?deep=1（下一步加）——
凭证有效性是外部事实，本地读配置文件是看不出来的。
"""

from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from app.agent.handoff import get_handoff, list_handoffs
from app.agent.orchestrator import handle
from app.config import BASE_DIR, get_settings
from app.llm import get_llm_service
from app.llm.base import LLMRequestError, LLMUnavailableError
from app.schemas import (
    ChatRequest,
    ChatResponse,
    HandoffDetail,
    HandoffRecord,
    HealthResponse,
)


class UTF8JSONResponse(JSONResponse):
    """显式声明 UTF-8。

    按 RFC 8259，JSON 默认就是 UTF-8，所以不带 charset 也合规；
    但 PowerShell 5.1 这类老客户端不看规范，会按 ISO-8859-1 解码成乱码。
    多写这半行，兼容性换来的麻烦远大于成本。
    """

    media_type = "application/json; charset=utf-8"


app = FastAPI(
    title="HelpDesk Agent",
    version="0.1.0",
    default_response_class=UTF8JSONResponse,
)

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


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    """一次对话。D1 只做路由 + 桩分支，不接检索和工具。"""
    return handle(req.message, req.session_id)


@app.get("/handoffs", response_model=list[HandoffRecord])
def handoffs(
    status: str | None = Query(None, description="pending / claimed / closed"),
    limit: int = Query(20, ge=1, le=200),
) -> list[HandoffRecord]:
    """人工侧入口：按状态拉交接单，最新的在前。"""
    try:
        return list_handoffs(status=status, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/handoffs/{handoff_id}", response_model=HandoffDetail)
def handoff_detail(handoff_id: str) -> HandoffDetail:
    """单条详情：带最近几轮对话，人工接手前先看上下文。"""
    record = get_handoff(handoff_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"交接单 {handoff_id} 不存在")
    return HandoffDetail(**record)
