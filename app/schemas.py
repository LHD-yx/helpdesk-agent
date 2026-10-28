"""API 层的数据契约。

业务代码内部不直接收发裸 dict：入参出参都在这里定义一次，
FastAPI 负责校验与生成 /docs，pydantic 负责类型转换与序列化。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class Intent(str, Enum):
    """三条业务通道。内部用英文常量，日志/评测/数据库都好用。"""

    POLICY_QA = "policy_qa"
    TICKET_OP = "ticket_op"
    HANDOFF = "handoff"


# 对外展示用中文；内部一律用 Intent 值。今天先放着，D5 前端会直接用。
INTENT_LABELS: dict[Intent, str] = {
    Intent.POLICY_QA: "政策问答",
    Intent.TICKET_OP: "工单处理",
    Intent.HANDOFF: "转人工",
}


class ChatRequest(BaseModel):
    """一次对话请求。"""

    message: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=64)


class ChatResponse(BaseModel):
    """一次对话响应。

    D1 只返回桩答案；citations / tool_trace 等字段等到真正有内容时再加，
    不提前占位——占位字段最后往往变成没人维护的死字段。
    """

    answer: str
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    session_id: str


class HealthResponse(BaseModel):
    """liveness 响应：进程活着、配置读到了、数据文件在不在。"""

    status: str
    provider: str
    model: str
    db_ready: bool
    # 下面两项只有 ?deep=1 才会填；为 None 就说明这次没做深度探测。
    llm_ready: bool | None = None
    llm_latency_ms: float | None = None
