"""意图路由：把一句用户话变成一个带置信度的意图。

三件事：分类（LLM）→ 解析（容错）→ 兜底策略（低置信度转人工）。
不接分支、不接 HTTP，那两件事在 orchestrator 里。
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field, ValidationError

from app.llm import get_llm_service
from app.schemas import Intent

# 低于这个值就转人工。调它之前先用评测集看准确率，别凭感觉。
CONFIDENCE_THRESHOLD = 0.7

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
    # re.I 让 JSON / Json / json 都能匹配——模型的大小写并不稳定。
    match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    return match.group(1).strip() if match else text


def parse_result(raw: str) -> IntentResult:
    """把模型原始输出解析成 IntentResult；解析失败就转人工。

    只抓"输入数据不合规"这两类异常。自己的 TypeError / NameError 应该原样抛出，
    否则真 bug 会被伪装成"模型又抽风了"。
    """
    try:
        data = json.loads(_strip_fences(raw))
        return IntentResult.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        return IntentResult(
            intent=Intent.HANDOFF,
            confidence=0.0,
            reason=f"路由解析失败：{exc}",
        )


def apply_policy(result: IntentResult) -> IntentResult:
    """低置信度转人工；保留原置信度与原意图，方便日志和评测。"""
    # 已经是安全出口（解析失败也会落到 HANDOFF），就不要再包一层：
    # 否则 "路由解析失败" 会被 "低置信度 0.00，原判 handoff" 覆盖，
    # 日志里就只剩一个毫无信息量的结论。
    if result.intent is Intent.HANDOFF:
        return result
    if result.confidence < CONFIDENCE_THRESHOLD:
        return IntentResult(
            intent=Intent.HANDOFF,
            confidence=result.confidence,
            reason=f"低置信度 {result.confidence:.2f}，原判 {result.intent.value}",
        )
    return result


def classify(message: str) -> IntentResult:
    """一次 LLM 调用，返回校验过、且过了兜底策略的意图。"""
    resp = get_llm_service().chat(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        temperature=0.0,
        response_format={"type": "json_object"},
    )
    return apply_policy(parse_result(resp.content))
