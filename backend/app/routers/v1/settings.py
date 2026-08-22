"""Settings Endpoint — read-only runtime config visibility.

GET /api/v1/settings/config
- Returns non-sensitive runtime config values for the Settings page.
- Secrets (API keys, tokens) are returned as boolean "has_key" only.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings

router = APIRouter(tags=["settings"])


class SettingsConfigResponse(BaseModel):
    """运行时配置只读快照。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "access": {
                        "api_key_set": False,
                        "cors_origins": "http://localhost:3002",
                        "rate_limit_enabled": True,
                        "rate_limit_requests": 100,
                    },
                    "weights": {"WEIGHT_AIRDROP_SIGNAL": 0.18},
                    "flags": {"ENABLE_LLM_ENHANCEMENT": False},
                    "sources": {"defillama": {"enabled": True, "has_api_key": False}},
                    "automation": {"SCHEDULER_ENABLED": True},
                    "platform": {"METRICS_ENABLED": True, "LOG_LEVEL": "info"},
                },
            }
        }
    )

    ok: bool = Field(True)
    data: dict = Field(...)


def _mask_key(val: str | None) -> bool:
    """Return True if a key-like setting is set, False otherwise."""
    return bool(val and val.strip())


def _safe_providers() -> list[dict[str, Any]]:
    """LLM provider 列表，**永不含明文 api_key**。

    `settings.llm_providers` 每个条目都带 `api_key` 原文；此前本端点直接把它塞进
    响应，配合 `/api/v1/auth/anonymous` 公开签发匿名 token，等于任何人零凭证就能
    取走 OPENAI_API_KEY。这里只保留运维需要的非敏感字段，并与
    `routers/v1/llm.py` 的脱敏口径保持一致（只暴露"是否已设置"）。
    """
    return [
        {
            "name": p.get("name", ""),
            "base_url": p.get("base_url", ""),
            "has_api_key": bool(p.get("api_key")),
            "models": p.get("models", []),
        }
        for p in settings.llm_providers
    ]


def _label_threshold(label: str) -> int:
    """取某个标签（FARM / WATCH）的分数下限。

    真值只有一处：`app.agents.scorer.LABEL_THRESHOLDS`。在这里做一次查表而不是
    抄一份常量，是因为这两个数已经被调过一次（v1.1：FARM 70 → 65）。抄一份就意味着
    下次再调时有两个地方要改，而漏改的那个不会报错、只会静默说谎。

    在函数内导入以避免与 scorer 形成模块级循环导入。
    """
    from app.agents.scorer import LABEL_THRESHOLDS

    for threshold, name in LABEL_THRESHOLDS:
        if name == label:
            return threshold
    # 标签名拼错时宁可让调用方看到 0，也不要静默返回一个像真值的数字
    return 0


@router.get(
    "/settings/config",
    response_model=SettingsConfigResponse,
    summary="运行时配置快照（只读）",
    description="返回当前运行时配置的非敏感值——布尔开关、URL、权重、超时；密钥只返回是否已设置。",
)
def get_settings_config() -> SettingsConfigResponse:
    """返回运行时配置快照。"""
    access: dict[str, Any] = {
        "api_key_set": _mask_key(settings.api_key),
        "cors_origins": settings.cors_origins or "",
        "cors_credentials": settings.cors_credentials,
        "rate_limit_enabled": settings.rate_limit_enabled,
        "rate_limit_requests": settings.rate_limit_requests,
        "rate_limit_window": settings.rate_limit_window,
        "app_env": settings.app_env,
    }

    # weight_version 是字符串（"v1.2"），与 8 个 float 权重同处一个字典，故用 Any
    weights: dict[str, Any] = {
        "WEIGHT_AIRDROP_SIGNAL": settings.weight_airdrop_signal,
        "WEIGHT_NARRATIVE_TIMING": settings.weight_narrative_timing,
        "WEIGHT_EXECUTION": settings.weight_execution,
        "WEIGHT_TEAM_REPUTATION": settings.weight_team_reputation,
        "WEIGHT_RISK": settings.weight_risk,
        "WEIGHT_TOKENOMICS": settings.weight_tokenomics,
        "WEIGHT_COMPETITION": settings.weight_competition,
        "WEIGHT_TRANSPARENCY": settings.weight_transparency,
        "weight_version": settings.weight_version,
    }

    flags: dict[str, bool] = {
        "ENABLE_LLM_ENHANCEMENT": settings.enable_llm_enhancement,
        "ENABLE_FEEDBACK_SYSTEM": settings.enable_feedback_system,
        "OPPORTUNITY_SHADOW_ENABLED": settings.opportunity_shadow_enabled,
        "OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED": settings.opportunity_economic_snapshot_enabled,
        "ENABLE_EVENTS_TRACKING": settings.enable_events_tracking,
        "ENABLE_USER_SYSTEM": settings.enable_user_system,
        "ENABLE_COMPETITION_CACHE": settings.enable_competition_cache,
        "METRICS_ENABLED": settings.metrics_enabled,
        "SCHEDULER_ENABLED": settings.scheduler_enabled,
        "COLLECTION_SCHEDULER_ENABLED": settings.collection_scheduler_enabled,
        "COLLECTION_AUTO_RUN_ENABLED": settings.collection_auto_run_enabled,
        "HEAT_SIGNAL_ENABLED": settings.heat_signal_enabled,
        "RATE_LIMIT_ENABLED": settings.rate_limit_enabled,
    }

    sources: dict[str, dict[str, Any]] = {
        "defillama": {
            "enabled": settings.defillama_enabled,
            "has_api_key": False,  # free API, no key needed
            "base_url": settings.defillama_base_url,
            "timeout": settings.defillama_timeout,
            "cron": settings.defillama_cron,
        },
        "github": {
            "enabled": settings.github_enabled,
            "has_api_key": _mask_key(settings.github_token),
            "base_url": settings.github_api_base_url,
            "timeout": settings.github_timeout,
            "cron": settings.github_cron,
        },
        "coingecko": {
            "enabled": settings.coingecko_enabled,
            "has_api_key": _mask_key(settings.coingecko_api_key),
            "base_url": settings.coingecko_api_base_url,
            "timeout": settings.coingecko_timeout,
            "cron": settings.coingecko_cron,
        },
        "twitter": {
            "enabled": settings.twitter_enabled,
            "has_api_key": _mask_key(settings.twitter_bearer_token),
            "timeout": settings.twitter_timeout,
            "keyword_cron": settings.twitter_keyword_cron,
            "kol_cron": settings.twitter_kol_cron,
        },
        "etherscan": {
            "enabled": settings.etherscan_enabled,
            "has_api_key": _mask_key(settings.etherscan_api_key),
            "timeout": settings.etherscan_timeout,
            "cron": settings.etherscan_cron,
        },
        "rootdata": {
            "enabled": settings.rootdata_enabled,
            "has_api_key": _mask_key(settings.rootdata_api_key),
            "base_url": settings.rootdata_base_url,
            "timeout": settings.rootdata_timeout,
            "cron": settings.rootdata_cron,
        },
        "cryptorank": {
            "enabled": settings.cryptorank_enabled,
            "has_api_key": _mask_key(settings.cryptorank_api_key),
            "base_url": settings.cryptorank_base_url,
            "timeout": settings.cryptorank_timeout,
            "cron": settings.cryptorank_cron,
        },
        "galxe": {
            "enabled": settings.galxe_enabled,
            "has_api_key": _mask_key(settings.galxe_api_key),
            "timeout": settings.galxe_timeout,
            "cron": settings.galxe_cron,
        },
        "layer3": {
            "enabled": settings.layer3_enabled,
            "has_api_key": _mask_key(settings.layer3_api_key),
            "timeout": settings.layer3_timeout,
            "cron": settings.layer3_cron,
        },
    }

    automation: dict[str, Any] = {
        "SCHEDULER_ENABLED": settings.scheduler_enabled,
        "COLLECTION_SCHEDULER_ENABLED": settings.collection_scheduler_enabled,
        "COLLECTION_AUTO_RUN_ENABLED": settings.collection_auto_run_enabled,
        "CRON_EXPRESSION": settings.cron_expression,
        "ANALYSIS_RUN_LIMIT": settings.analysis_run_limit,
        "RAW_PROJECTS_RETENTION_DAYS": settings.raw_projects_retention_days,
        "PROJECT_SIGNALS_RETENTION_DAYS": settings.project_signals_retention_days,
        "COLLECTION_LOGS_RETENTION_DAYS": settings.collection_logs_retention_days,
        "UNPROCESSED_RAW_RETENTION_DAYS": settings.unprocessed_raw_retention_days,
        "RAW_ARCHIVE_RETENTION_DAYS": settings.raw_archive_retention_days,
        "SIGNALS_ARCHIVE_RETENTION_DAYS": settings.signals_archive_retention_days,
        "ARCHIVE_SCHEDULER_ENABLED": settings.archive_scheduler_enabled,
        "ARCHIVE_CRON": settings.archive_cron,
        "SCHEDULER_MISFIRE_GRACE_SECONDS": settings.scheduler_misfire_grace_seconds,
    }

    platform: dict[str, Any] = {
        "METRICS_ENABLED": settings.metrics_enabled,
        "METRICS_PATH": settings.metrics_path,
        "LOG_LEVEL": settings.log_level,
        "LOG_FORMAT": settings.log_format,
        "OTEL_ENABLED": settings.otel_enabled,
        "OTEL_SERVICE_NAME": settings.otel_service_name,
        "DB_BACKEND": settings.db_backend,
        "APP_ENV": settings.app_env,
    }

    thresholds: dict[str, float] = {
        "DISCOVERY_SCORE_ANALYSIS_THRESHOLD": settings.discovery_score_analysis_threshold,
        "CONFIDENCE_THRESHOLD": settings.confidence_threshold,
        "MISSING_FIELDS_THRESHOLD": settings.missing_fields_threshold,
        "LLM_DISCOVERY_SCORE_THRESHOLD": settings.llm_discovery_score_threshold,
        "LLM_DAILY_BUDGET_USD": settings.llm_daily_budget_usd,
        "LLM_TEMPERATURE": settings.llm_temperature,
        "LLM_MAX_TOKENS": settings.llm_max_tokens,
        # 标签分档来自 scorer.LABEL_THRESHOLDS（不是环境变量）。之所以要在这里
        # 暴露出去：前端项目详情页原本把「FARM≥65 / WATCH≥50」写死在文案里，
        # 而这两个数**已经改过一次**（v1.1 把 FARM 从 70 下调到 65）。
        # 写死的文案不会跟着改，只会静默变成错的。
        "LABEL_FARM_THRESHOLD": float(_label_threshold("FARM")),
        "LABEL_WATCH_THRESHOLD": float(_label_threshold("WATCH")),
    }

    return SettingsConfigResponse(
        ok=True,
        data={
            "access": access,
            "weights": weights,
            "flags": flags,
            "sources": sources,
            "automation": automation,
            "platform": platform,
            "thresholds": thresholds,
            "llm": {
                "enabled": settings.is_llm_enabled,
                "temperature": settings.llm_temperature,
                "max_tokens": settings.llm_max_tokens,
                "daily_budget_usd": settings.llm_daily_budget_usd,
                "discovery_score_threshold": settings.llm_discovery_score_threshold,
                "providers": _safe_providers(),
            },
        },
    )
