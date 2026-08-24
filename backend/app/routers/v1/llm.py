"""LLM status endpoint — multi-provider / multi-model failover config visibility.

GET /api/v1/llm/status
返回当前 LLM 多接口故障转移配置（API key 脱敏）。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter

from app.config import settings

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["llm"])


def _mask_key(key: str) -> str:
    """脱敏 API key：只显示前 4 位和后 4 位。"""
    if not key:
        return ""
    if len(key) <= 12:
        return key[:2] + "***" + key[-2:] if len(key) > 4 else "***"
    return key[:4] + "***" + key[-4:]


@router.get(
    "/llm/status",
    summary="LLM 多接口故障转移状态",
    description="返回当前 LLM 配置：接口列表、每接口模型列表、故障转移策略、是否已启用。",
)
def llm_status():
    """获取 LLM 多接口/多模型配置状态。

    返回每个接口的 base_url、脱敏 api_key、模型列表、名称。
    不暴露原始 API key。
    """
    providers = settings.llm_providers

    provider_list = []
    for p in providers:
        provider_list.append(
            {
                "name": p["name"],
                "base_url": p["base_url"],
                "api_key_masked": _mask_key(p.get("api_key", "")),
                "has_api_key": bool(p.get("api_key")),
                "models": p.get("models", []),
                "model_count": len(p.get("models", [])),
            }
        )

    total_models = sum(p["model_count"] for p in provider_list)

    # 当日花费。此前这个接口只回显 daily_budget_usd —— 一个"配置里写了多少"，
    # 而看不到"已经花了多少"。只有上限没有用量，运维无法判断还剩多少余量，
    # 也无法发现预算根本没在累计（那正是 2026-08-24 之前的真实状况）。
    #
    # 读账本失败不能让这个诊断接口 500：它恰恰是排查账本问题时要看的地方。
    # 失败时把 spend_today_usd 置 None 并给出 ledger_error，让"读不出来"
    # 和"确实是 0"区分得开 —— 两者都返回 0 的话，一个坏掉的账本看起来
    # 就像一个还没花钱的账本。
    spend_today: float | None = None
    calls_today: int | None = None
    ledger_error: str | None = None
    try:
        from app.llm.budget import get_daily_spend

        spend = get_daily_spend()
        spend_today = float(spend.cost_usd)
        calls_today = spend.calls
    except Exception as exc:
        ledger_error = str(exc)[:200]
        logger.warning("llm.status.ledger_unavailable", error=ledger_error)

    return {
        "ok": True,
        "data": {
            "enabled": settings.is_llm_enabled,
            "provider_count": len(provider_list),
            "total_model_count": total_models,
            "failover_strategy": "provider1+model1 → provider1+model2 → provider2+model1 → ...",
            "providers": provider_list,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "daily_budget_usd": settings.llm_daily_budget_usd,
            # 预算是否真的会拦：0 或负数表示不限额。
            "budget_enforced": settings.llm_daily_budget_usd > 0,
            "spend_today_usd": spend_today,
            "calls_today": calls_today,
            "ledger_error": ledger_error,
            "discovery_score_threshold": settings.llm_discovery_score_threshold,
        },
    }
