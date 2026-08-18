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
        provider_list.append({
            "name": p["name"],
            "base_url": p["base_url"],
            "api_key_masked": _mask_key(p.get("api_key", "")),
            "has_api_key": bool(p.get("api_key")),
            "models": p.get("models", []),
            "model_count": len(p.get("models", [])),
        })

    total_models = sum(p["model_count"] for p in provider_list)

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
            "discovery_score_threshold": settings.llm_discovery_score_threshold,
        },
    }
