"""Project Runway & Funding Viability Gate service.

针对低迷 Web3 市场行情，对项目融资规模、机构背书、跑道时效与开发活跃度进行纯确定性评估：
1. 微额融资与缺乏知名机构背书（LOW_FUNDING_UNVIABLE）
2. 跑道耗尽与开发停摆（RUNWAY_DEPLETED）
3. 无背书纯积分盘/幽灵盘（UNBACKED_POINTS_MACHINE）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from app.services.funding import classify_investor_tier

LOW_FUNDING_UNVIABLE = "LOW_FUNDING_UNVIABLE"
RUNWAY_DEPLETED = "RUNWAY_DEPLETED"
UNBACKED_POINTS_MACHINE = "UNBACKED_POINTS_MACHINE"

ViabilityTier = Literal["viable", "borderline", "unviable"]

VIABILITY_TIER_ZH: dict[ViabilityTier, str] = {
    "viable": "资金充裕",
    "borderline": "跑道观察",
    "unviable": "存活预警",
}

VIABILITY_REASON_ZH: dict[str, str] = {
    LOW_FUNDING_UNVIABLE: "公开融资 < $3M 且缺乏顶级机构背书，低迷行情下极易倒闭",
    RUNWAY_DEPLETED: "距离上次小额融资已超 18 个月且开发停摆，跑道资金基本耗尽",
    UNBACKED_POINTS_MACHINE: "零融资/未知背景却开启积分盘，无实质 TVL 支撑，归零风险极高",
}


def _months_since(date_str: str | None, now: datetime | None = None) -> float | None:
    """计算自特定日期（YYYY-MM-DD 或 ISO）至今的月数。"""
    if not date_str:
        return None
    now_dt = now or datetime.now(UTC)
    clean_str = date_str.strip().split("T")[0]
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m", "%Y"):
        try:
            d = datetime.strptime(clean_str, fmt).replace(tzinfo=UTC)
            delta = now_dt - d
            return max(0.0, delta.days / 30.4375)
        except ValueError:
            continue
    return None


def evaluate_project_viability(
    *,
    funding_total_usd: float | None = None,
    funding_tier: str | None = None,
    funding_rounds: int = 0,
    funding_last_date: str | None = None,
    funding_investors: list[str] | tuple[str, ...] = (),
    funding_lead_investors: list[str] | tuple[str, ...] = (),
    github_inactive_days: int | None = None,
    tvl_usd: float | None = None,
    has_points_program: bool = False,
    stage: str = "ideation",
    now: datetime | None = None,
) -> dict[str, Any]:
    """确定性评估项目在低迷行情下的存活率与跑道健康度。"""
    tier_norm = (funding_tier or "unknown").lower().strip()
    if tier_norm in ("unknown", "none", ""):
        all_investors = list(funding_investors) + list(funding_lead_investors)
        if all_investors:
            inv_tier = classify_investor_tier(all_investors)
            if inv_tier and inv_tier != "unknown":
                tier_norm = inv_tier

    reasons: list[str] = []

    # 1. 检验：微额融资且无知名机构背书
    # 在熊市中，融资金额 < $3M 且无 Tier-1/Tier-2 机构背书的项目很难撑到 TGE 发币
    if funding_total_usd is not None and 0 < funding_total_usd < 3_000_000:
        if tier_norm not in ("tier1", "tier2"):
            reasons.append("LOW_FUNDING_UNVIABLE")

    # 2. 检验：跑道资金耗尽（上次融资久远 + 融资金额偏小 + 开发停摆或无 TVL）
    months_ago = _months_since(funding_last_date, now=now)
    if months_ago is not None and months_ago >= 18.0:
        is_small_raise = funding_total_usd is not None and funding_total_usd < 5_000_000
        is_stagnant = (github_inactive_days is not None and github_inactive_days >= 60) or (
            tvl_usd is not None and tvl_usd < 100_000
        )
        if is_small_raise and is_stagnant and tier_norm != "tier1":
            reasons.append("RUNWAY_DEPLETED")

    # 3. 检验：无背书纯积分盘（零/未知融资 + 无机构 + 搞 points + TVL 极低）
    has_no_funding = funding_total_usd is None or funding_total_usd <= 0
    has_no_tier = tier_norm in ("none", "unknown", "tier3")
    tvl_negligible = tvl_usd is None or tvl_usd < 50_000
    if has_points_program and has_no_funding and has_no_tier and tvl_negligible:
        reasons.append("UNBACKED_POINTS_MACHINE")

    # 判定分档
    tier: ViabilityTier
    if reasons:
        tier = "unviable"
    elif (
        (funding_total_usd is not None and 3_000_000 <= funding_total_usd < 5_000_000 and tier_norm != "tier1")
        or (months_ago is not None and 12.0 <= months_ago < 18.0 and tier_norm != "tier1")
        or (has_no_funding and tier_norm not in ("tier1", "tier2"))
    ):
        tier = "borderline"
    else:
        tier = "viable"

    reasons_zh = tuple(VIABILITY_REASON_ZH.get(r, r) for r in reasons)
    if tier == "unviable":
        recommendation_zh = "项目融资过小或缺乏知名机构支持，在当前低迷行情下存活至发币的概率极低，建议坚决规避。"
    elif tier == "borderline":
        recommendation_zh = "项目资金跑道相对偏紧或融资披露偏早，建议严格控制单钱包交互成本，密切追踪最新动态。"
    else:
        recommendation_zh = "项目融资规模充足或具备头部机构背书，具备相对稳健的存活跑道。"

    return {
        "tier": tier,
        "reasons": tuple(reasons),
        "reasons_zh": reasons_zh,
        "recommendation_zh": recommendation_zh,
    }
