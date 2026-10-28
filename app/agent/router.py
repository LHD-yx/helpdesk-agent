"""意图路由：把一句用户话变成一个带置信度的意图。

今天只做一件事——分类。不接分支、不接 HTTP。
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field

from app.llm import get_llm_service
from app.schemas import Intent

SYSTEM_PROMPT = """你是企业服务台的意图分类器。只输出 JSON，不要输出任何其他文字。

可选的 intent：
- policy_qa：询问公司政策、制度、流程、报销标准、假期规则
- ticket_op：查询、创建、升级工单；报修设备故障（电脑开不了机、网络断、打印机坏了等）
- handoff：投诉、要求人工、情绪激烈、超出以上范围、无法判断

输出格式：
{"intent": "<policy_qa|ticket_op|handoff>", "confidence": <0到1的小数>, "reason": "<不超过20字>"}

示例：
用户：报销流程是什么
输出：{"intent": "policy_qa", "confidence": 0.95, "reason": "询问制度流程"}
用户：T1001 到哪一步了
输出：{"intent": "ticket_op", "confidence": 0.92, "reason": "查询指定工单"}
用户：我电脑开不了机
输出：{"intent": "ticket_op", "confidence": 0.95, "reason": "设备故障需报修建单"}
用户：叫你们领导来
输出：{"intent": "handoff", "confidence": 0.9, "reason": "情绪激动要求人工"}
"""


class IntentResult(BaseModel):
    """路由结果。和 schemas.ChatResponse 里的三个字段对齐，方便直接塞进去。"""

    intent: Intent
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


def _strip_fences(text: str) -> str:
    """模型常把 JSON 包在 ```json 里，先剥掉围栏再解析。"""
    text = text.strip()
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return match.group(1).strip() if match else text


def classify(message: str) -> IntentResult:
    """一次 LLM 调用，返回校验过的意图。

    解析失败时**直接抛异常**，不在这里静默兜底——
    静默兜底会把"模型输出坏了"伪装成"用户要转人工"。
    真正的降级策略在 B3 的改错环节里加。
    """
    resp = get_llm_service().chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    data = json.loads(_strip_fences(resp.content))
    return IntentResult.model_validate(data)
