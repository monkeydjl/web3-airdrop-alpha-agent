"""Project AI chat: grounded multi-turn Q&A about a single project.

与 ai_brief（一次性独白）互补：对话让用户追问「为什么是这个分」「参与风险
是什么」这类静态面板答不了的问题。答案必须基于系统自己的结构化数据
（system prompt 注入项目快照），而不是模型的记忆 —— 数据里没有的就说没有。

对话没有规则引擎可回退（自由问答无法用模板拼），所以降级只有
llm_disabled / budget_exceeded / llm_error 三态，`reply` 为 None。
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.config import settings
from app.services.ai_brief import build_rule_brief

logger = structlog.get_logger(__name__)

# 单次请求携带的最大历史消息数（不含 system），12 条 = 6 轮问答。
# 轮数再往上，成本线性涨而答案质量基本不涨 —— 更早的上下文对
# 「针对当前项目追问」几乎没有增量。前端持有的完整历史不受影响。
CHAT_MAX_HISTORY_MESSAGES = 12

# 服务端单条消息长度上限。前端输入框限 500 字，这里是兜底，
# 防止绕过前端的调用把单轮 token 成本抬起来。
CHAT_MAX_MESSAGE_CHARS = 2000

# 一次请求允许的消息总数上限。
CHAT_MAX_MESSAGES = 20


def _parse_json(value: Any) -> Any:
    if value is None or value == "":
        return None
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _payload_ctx(project: dict[str, Any]) -> dict[str, Any]:
    """注入 system prompt 的项目快照。字段与 ai_brief 的 LLM 上下文一致，
    外加融资字段 —— 追问里「融资情况怎么样」是高频问题。"""
    investors = project.get("funding_investors") or []
    if not isinstance(investors, list):
        investors = []
    return {
        "name": project.get("name"),
        "sector": project.get("sector"),
        "stage": project.get("stage"),
        "source": project.get("source"),
        "score": project.get("score"),
        "label": project.get("label"),
        "confidence": project.get("confidence"),
        "reasons": _parse_json(project.get("reason")),
        "narrative": _parse_json(project.get("narrative_json")),
        "team": _parse_json(project.get("team_json")),
        "risk": _parse_json(project.get("risk_json")),
        "tokenomics": _parse_json(project.get("tokenomics_json")),
        "funding": {
            "quality": project.get("funding_quality"),
            "tier": project.get("funding_tier"),
            "total_usd": project.get("funding_total_usd"),
            "investors": investors[:5],
        },
        "rule_brief_bullets": build_rule_brief(project).get("bullets") or [],
    }


async def generate_chat_reply(
    project: dict[str, Any],
    history: list[dict[str, str]],
) -> dict[str, Any]:
    """针对单个项目的多轮问答。返回 `{"reply": str | None, "degraded_reason": str | None}`。

    历史由前端持有、随请求传入，服务端无状态；这里只保留最近
    `CHAT_MAX_HISTORY_MESSAGES` 条发给模型。
    """
    if not settings.is_llm_enabled:
        return {"reply": None, "degraded_reason": "llm_disabled"}

    name = project.get("name")
    trimmed = history[-CHAT_MAX_HISTORY_MESSAGES:]
    payload = _payload_ctx(project)

    system = (
        "你是 Web3 空投研究助手，正在与用户就下面数据里的这一个项目做多轮追问分析。\n"
        "要求：\n"
        "1) 只依据提供的项目数据与系统评分回答；数据里没有的信息（融资额、审计、具体任务等）"
        "不要编造，明确说数据里没有；\n"
        "2) 直接回应用户的追问，不要每次都把完整解读重复一遍；\n"
        "3) 涉及「该不该参与」时给出依据与风险，但必须说明不构成投资建议；\n"
        "4) 用简洁的中文。\n\n"
        f"项目数据：\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```"
    )
    messages = [{"role": "system", "content": system}, *trimmed]

    try:
        from app.llm.client import llm_chat

        result = await llm_chat(
            messages=messages,
            temperature=float(settings.llm_temperature),
            max_tokens=max(400, int(settings.llm_max_tokens)),
        )
        content = result.text
        if content and str(content).strip():
            return {"reply": str(content).strip(), "degraded_reason": None}
        if result.refused_reason:
            # refused_reason 只在被预算闸门拦下时非空 —— 与接口故障分开，
            # 两者的处置动作完全不同（见 ai_brief.try_llm_brief 的说明）。
            logger.info("ai_chat.degraded_by_budget", project=name, reason=result.refused_reason)
            return {"reply": None, "degraded_reason": result.refused_reason}
    except Exception as e:
        logger.warning("ai_chat.llm_failed", error=str(e), project=name)
        return {"reply": None, "degraded_reason": "llm_error"}
    return {"reply": None, "degraded_reason": "llm_error"}
