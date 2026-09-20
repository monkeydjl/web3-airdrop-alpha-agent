"""公开的评分方法论快照 — GET /api/v1/public-config。

**存在理由**：前端项目详情页要展示"这个分是按什么权重、什么阈值算出来的"，
而这两组数**已经被调过**（v1.1 把 FARM 从 70 下调到 65，权重也随校准变动）。
写死在前端文案里的数字不会跟着改，只会静默变成错的。

**为什么不直接用 `/settings/config`**：那个端点回显 `has_api_key`（哪些密钥
已配置）、各源 `base_url`、全部 cron 表达式、LLM 预算与兜底单价、`DB_BACKEND`
与 `APP_ENV` —— 是一份完整的基础设施画像，必须留在管理员锁后面
（`ADMIN_ONLY_PREFIXES` 含 `/api/v1/settings`）。

此前前端代理把管理员密钥无差别注入所有 `/api/*` 请求，于是项目详情页这种
面向普通访客的页面也能读到那份画像。拆出本端点是把"展示评分方法论"这个
真实需求与"读取运行时配置"这个管理动作分开，前端代理才有可能只给管理动作
注入密钥（见 ACTION_LOOP_DESIGN / GO_LIVE_CHECKLIST 的前端鉴权一节）。

**白名单而非整块转发**：`thresholds` 块里混着 `LLM_DAILY_BUDGET_USD`、
`LLM_FALLBACK_PRICE_PER_1M_USD` 这类成本配置。整块转发会顺带公开预算信息，
所以这里逐个列出要暴露的键 —— 将来给 `/settings/config` 加字段时，
本端点不会跟着漏。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings

# 复用 settings.py 的阈值查表，**不抄第三份**。
#
# `LABEL_THRESHOLDS` 是 `list[tuple[int, str]]` 而非 dict，要遍历匹配 ——
# 我第一版凭印象写成 `.get(label, 0)`，直接 AttributeError（实测踩到）。
# 那恰好印证了原版注释里的道理：真值只有一处，抄一份就多一个会走偏的地方。
# 这里连查表逻辑一并复用，两个端点报的阈值永远不可能不一致。
from app.routers.v1.settings import _label_threshold

router = APIRouter(tags=["settings"])


class PublicConfigResponse(BaseModel):
    """评分方法论快照（无敏感信息）。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "weights": {
                        "WEIGHT_AIRDROP_SIGNAL": 0.18,
                        "weight_version": "v1.3",
                    },
                    "thresholds": {
                        "LABEL_FARM_THRESHOLD": 65.0,
                        "LABEL_WATCH_THRESHOLD": 50.0,
                        "CONFIDENCE_THRESHOLD": 0.5,
                    },
                },
            }
        }
    )

    ok: bool = Field(True)
    data: dict[str, Any] = Field(...)


@router.get(
    "/public-config",
    response_model=PublicConfigResponse,
    summary="评分方法论快照（公开）",
    description=(
        "返回 8 维权重、权重版本号与标签分档阈值 —— 前端展示「这个分怎么来的」所需。"
        "**不含**任何密钥状态、采集源地址、cron、LLM 预算或环境标识；"
        "那些在管理员专用的 `GET /api/v1/settings/config` 里。"
    ),
)
def get_public_config() -> PublicConfigResponse:
    """公开可读的评分方法论。

    这里的字段是**白名单**，新增前先问一句：匿名访客看到它有没有风险？
    权重与阈值本身就写在 docs/DATA_SCORING_DICT.md 里，公开无损；
    而任何带"哪些密钥配了""连的哪个库""预算多少"语义的字段都不属于这里。
    """
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

    # 只有展示评分结果时必需的三个。刻意**不含** LLM_DAILY_BUDGET_USD /
    # LLM_FALLBACK_PRICE_PER_1M_USD / LLM_TEMPERATURE 等成本与调参项 ——
    # 它们在 /settings/config 的同名 thresholds 块里，属于运维信息。
    thresholds: dict[str, float] = {
        "LABEL_FARM_THRESHOLD": float(_label_threshold("FARM")),
        "LABEL_WATCH_THRESHOLD": float(_label_threshold("WATCH")),
        "CONFIDENCE_THRESHOLD": settings.confidence_threshold,
    }

    return PublicConfigResponse(ok=True, data={"weights": weights, "thresholds": thresholds})
