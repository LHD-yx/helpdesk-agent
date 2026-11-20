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
    # 空 = 无状态、不共享记忆。绝不能给一个共享默认值，
    # 否则所有匿名用户会共用同一份历史（串号 + 数据泄漏）。
    session_id: str = Field(default="", max_length=64)


class Citation(BaseModel):
    """一条引用。由检索结果拼出来，不是模型自己写的。"""

    policy_id: str
    title: str
    section: str
    source_file: str
    snippet: str
    score: float


class Step(BaseModel):
    """一次执行动作。给前端展示「它做了什么」，而不是只给一段答案。

    action 用工具名或动作名（get_ticket / retrieve_policy / handoff），
    detail 是人话摘要，ok=false 表示这一步失败了。
    """

    action: str
    detail: str
    ok: bool = True


class ChatResponse(BaseModel):
    """一次对话响应。"""

    answer: str
    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    session_id: str
    citations: list[Citation] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)

    # ---- 可观测性：一次请求的身份与健康状态 ----
    request_id: str = ""
    served_by: str = ""      # 最终答案由哪个 provider 产出
    degraded: bool = False   # 本次请求中是否发生过降级（任一环节）
    fallback: bool = False
    fallback_reason: str = ""


class HealthResponse(BaseModel):
    """liveness 响应：进程活着、配置读到了、数据文件在不在。"""

    status: str
    provider: str
    model: str
    db_ready: bool
    # 下面两项只有 ?deep=1 才会填；为 None 就说明这次没做深度探测。
    llm_ready: bool | None = None
    llm_latency_ms: float | None = None
