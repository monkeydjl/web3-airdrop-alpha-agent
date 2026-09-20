"""Anti-PUA, Capital Friction, and Exit Advisory service.

Pure deterministic logic for:
1. Fatigue & Dilution Index calculation (Anti-PUA)
2. Capital Friction Tier classification (Zero-Cost / Low-Cost / Heavy-Capital)
3. Exit & Stop-Loss Advisory triggers
"""

from __future__ import annotations

from typing import Any, Literal

FrictionTier = Literal["zero_cost", "low_cost", "medium_cost", "heavy_capital"]
FatigueLevel = Literal["low", "medium", "high", "critical"]

FATIGUE_LEVEL_ZH: dict[FatigueLevel, str] = {
    "low": "健康早期",
    "medium": "成熟观望",
    "high": "高疲劳预警",
    "critical": "严重 PUA 风险",
}

FRICTION_TIER_ZH: dict[FrictionTier, str] = {
    "zero_cost": "零资金成本",
    "low_cost": "极低磨损",
    "medium_cost": "中度磨损",
    "heavy_capital": "重度质押/高磨损",
}

EXIT_REASON_ZH: dict[str, str] = {
    "TVL_DRAIN": "30 天内 TVL 持续大额净流出 (>30%)",
    "DEV_INACTIVE": "GitHub 核心仓库连续 60 天无代码提交",
    "SITE_OFFLINE": "核心官网或交互门户连续 72 小时无法访问",
    "RULE_WORSE": "官方大幅上调提现门槛或引入质押罚没条款",
}


def calculate_fatigue_index(
    duration_months: float = 0.0,
    season_count: int = 1,
    tge_transparency: str = "unannounced",
    lockup_days: int = 0,
) -> float:
    """Calculate the Anti-PUA Fatigue & Dilution index [0.0, 1.0].

    Weights:
    - 0.35: Points duration
    - 0.25: Points season inflation / dilution
    - 0.25: TGE timeline clarity
    - 0.15: Required capital lockup period
    """
    # 1. Duration factor
    if duration_months < 3.0:
        f_duration = 0.10
    elif duration_months < 6.0:
        f_duration = 0.35
    elif duration_months < 9.0:
        f_duration = 0.70
    else:
        f_duration = 0.95

    # 2. Season count factor (dilution)
    if season_count <= 1:
        f_season = 0.10
    elif season_count == 2:
        f_season = 0.50
    else:
        f_season = 0.90

    # 3. TGE transparency factor
    tge_clean = tge_transparency.lower().strip()
    if tge_clean in ("confirmed_quarter", "confirmed", "clear"):
        f_tge = 0.10
    elif tge_clean in ("vague_soon", "soon", "delayed"):
        f_tge = 0.50
    else:
        f_tge = 0.85

    # 4. Capital lockup factor
    if lockup_days <= 0:
        f_lockup = 0.10
    elif lockup_days <= 30:
        f_lockup = 0.40
    else:
        f_lockup = 0.85

    index = 0.35 * f_duration + 0.25 * f_season + 0.25 * f_tge + 0.15 * f_lockup
    return round(max(0.0, min(1.0, index)), 2)


def get_fatigue_level(index: float) -> FatigueLevel:
    """Map fatigue index float to level enum."""
    if index < 0.35:
        return "low"
    if index < 0.60:
        return "medium"
    if index < 0.80:
        return "high"
    return "critical"


def classify_capital_friction_tier(
    has_testnet: bool = False,
    hard_cost_usd: float | None = None,
    capital_at_risk_usd: float | None = None,
    is_perp: bool = False,
) -> FrictionTier:
    """Classify capital friction into 4 tiers."""
    if (capital_at_risk_usd is not None and capital_at_risk_usd >= 500) or (
        hard_cost_usd is not None and hard_cost_usd >= 50
    ) or is_perp:
        return "heavy_capital"

    if (hard_cost_usd is not None and hard_cost_usd > 10) or (
        capital_at_risk_usd is not None and capital_at_risk_usd > 50
    ):
        return "medium_cost"

    if has_testnet and (capital_at_risk_usd is None or capital_at_risk_usd <= 5) and (hard_cost_usd is None or hard_cost_usd <= 5):
        return "zero_cost"

    if (hard_cost_usd is not None and hard_cost_usd <= 10) or (
        not has_testnet and hard_cost_usd is not None
    ):
        return "low_cost"

    # Default to zero_cost if pure testnet or minimal/unknown hard cost
    return "zero_cost"


def evaluate_exit_advisory(
    tvl_drain_ratio: float | None = None,
    github_inactive_days: int | None = None,
    site_alive: bool | None = None,
    rule_worsened: bool = False,
) -> dict[str, Any]:
    """Evaluate whether project triggers Exit & Stop-Loss Advisory."""
    reasons: list[str] = []

    if tvl_drain_ratio is not None and tvl_drain_ratio >= 0.30:
        reasons.append("TVL_DRAIN")

    if github_inactive_days is not None and github_inactive_days >= 60:
        reasons.append("DEV_INACTIVE")

    if site_alive is False:
        reasons.append("SITE_OFFLINE")

    if rule_worsened:
        reasons.append("RULE_WORSE")

    active = len(reasons) > 0
    severity: Literal["critical", "warning", "none"]
    if not active:
        severity = "none"
    elif "SITE_OFFLINE" in reasons or "TVL_DRAIN" in reasons:
        severity = "critical"
    else:
        severity = "warning"

    reasons_zh = tuple(EXIT_REASON_ZH.get(r, r) for r in reasons)
    recommendation_zh = (
        "由于项目发展出现显著恶化/停摆迹象，建议立即赎回质押资产并停止交互。"
        if active
        else ""
    )

    return {
        "active": active,
        "reasons": tuple(reasons),
        "reasons_zh": reasons_zh,
        "severity": severity,
        "recommendation_zh": recommendation_zh,
    }
