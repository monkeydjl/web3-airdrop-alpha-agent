from datetime import datetime
from typing import Any

from app.opportunity.evidence import SOURCE_GRADE_WEIGHT, resolve_factor
from app.opportunity.models import (
    EvidenceRecord,
    OpportunityInputs,
    OpportunityProfile,
    ProbabilityRange,
)

EVENT_RULES = {
    "official_distribution_and_catalyst": ProbabilityRange(low=0.65, base=0.78, high=0.90),
    "official_distribution": ProbabilityRange(low=0.55, base=0.70, high=0.85),
    "official_points_value": ProbabilityRange(low=0.50, base=0.65, high=0.80),
}

ELIGIBILITY_RULES = {
    "deterministic_open_within_budget": ProbabilityRange(low=0.65, base=0.80, high=0.90),
    "points_open_within_budget": ProbabilityRange(low=0.50, base=0.67, high=0.82),
    "behavioral_open_within_budget": ProbabilityRange(low=0.40, base=0.58, high=0.75),
}

SURVIVAL_RULES = {
    "allowed": ProbabilityRange(low=0.75, base=0.88, high=0.95),
    "not_forbidden": ProbabilityRange(low=0.60, base=0.75, high=0.88),
    "forbidden": ProbabilityRange(low=0.0, base=0.0, high=0.0),
}


def joint_probability(
    event: ProbabilityRange,
    eligibility: ProbabilityRange,
    survival: ProbabilityRange,
) -> ProbabilityRange:
    """三因子联合概率（假设三者相互独立）。

    `base` 取三者相乘——这是独立性假设下的正确联合期望。

    区间端点**不能**同样逐分位相乘：`low×low×low` 只有在三个因子完全同向
    （perfect comonotonicity）时才成立，与 `base` 所依赖的独立性假设直接矛盾，
    两者不可能同时为真。逐分位连乘会把不确定度过度累积：以最佳规则栈
    (0.65/0.78/0.90 × 0.65/0.80/0.90 × 0.75/0.88/0.95) 为例，40 万次蒙特卡洛
    （各因子独立三角分布）的真实 p10–p90 是 0.4528–0.5953，而逐分位连乘给出
    0.3169–0.7695——两个端点都落在约 0% 的尾部，区间宽度虚高约 1.6 倍。

    后果不只是"看起来不准"：`decision` 用 `reward_probability.low >= 0.20` 作为
    FARM 门槛，三重下界连乘会让"官方分发+积分制"这类中档规则栈的 joint.low
    恒为 0.1650，**永远无法通过门槛**，纯粹是数学假象而非项目本身的问题。

    这里改为在独立性假设下按相对不确定度做平方和合成（误差独立时的标准做法）：
        rel_low  = sqrt(Σ ((base_i - low_i)  / base_i)^2)
        rel_high = sqrt(Σ ((high_i - base_i) / base_i)^2)
    同一算例下给出 0.3893–0.6664，仍偏保守（覆盖率 99.2%），但不再自相矛盾，
    中档规则栈的 joint.low 回到 0.2154，重新可达。
    """
    factors = (event, eligibility, survival)
    base = event.base * eligibility.base * survival.base
    # 逐分位连乘的结果同时作为**兜底端点**：它是完全同向假设下的区间，在独立性
    # 假设下必然更宽（更保守），因此可以安全地当作下界的地板、上界的天花板。
    comonotone_low = event.low * eligibility.low * survival.low
    comonotone_high = event.high * eligibility.high * survival.high

    if base <= 0.0:
        # 任一因子 base 为 0（如 survival=forbidden）则联合期望为 0。
        # 但端点不必同时为 0：base=0 只说明"最可能不发生"，若某因子 high>0，
        # 乐观端仍应保留——否则 `gross_reward.high` 被强行归零，会经
        # DUST_REWARD 门槛把项目误判成 30 天 IGNORE。
        return ProbabilityRange(low=comonotone_low, base=0.0, high=comonotone_high)

    rel_low_sq = 0.0
    rel_high_sq = 0.0
    for factor in factors:
        if factor.base <= 0.0:
            continue
        rel_low_sq += ((factor.base - factor.low) / factor.base) ** 2
        rel_high_sq += ((factor.high - factor.base) / factor.base) ** 2

    low = base * (1.0 - rel_low_sq**0.5)
    high = base * (1.0 + rel_high_sq**0.5)

    # 相对不确定度合成后可能超过 100%（例如某因子 low=0），此时 low 会被压到
    # 负数再夹到 0——那比逐分位连乘还悲观，与"合成区间不得比连乘更宽"的前提
    # 相矛盾。用连乘端点兜底，保证新区间恒为旧区间的子集。
    low = min(max(low, comonotone_low), base)
    high = max(min(high, comonotone_high), base)

    # 夹紧到 [0,1] 并保持 low <= base <= high
    low = min(max(low, 0.0), base)
    high = max(min(high, 1.0), base)
    return ProbabilityRange(low=low, base=base, high=high)


def derive_probability_inputs(
    inputs: OpportunityInputs,
    evidence: list[EvidenceRecord],
    profile: OpportunityProfile,
    now: datetime | None = None,
) -> tuple[ProbabilityRange | None, ProbabilityRange | None, ProbabilityRange | None]:
    normalized = _resolved_factors(inputs, evidence, now)
    event = _explicit_range(normalized.get("event_probability")) or _derive_event(normalized)
    eligibility = _explicit_range(normalized.get("eligibility_probability")) or _derive_eligibility(normalized, profile)
    policy_item = normalized.get("multiwallet_policy")
    survival = _explicit_range(normalized.get("survival_probability"))
    if survival is None and policy_item is not None and _approved(policy_item, minimum_grade="B"):
        survival = SURVIVAL_RULES.get(policy_item[1])
    return event, eligibility, survival


def _resolved_factors(
    inputs: OpportunityInputs,
    evidence: list[EvidenceRecord],
    now: datetime | None,
) -> dict[str, tuple[EvidenceRecord, Any]]:
    accepted_ids = set(inputs.evidence_ids)
    current = [
        record for record in evidence if record.evidence_id in accepted_ids and record.project_id == inputs.project_id
    ]
    resolved = {}
    for factor_key in {
        "event_probability",
        "eligibility_probability",
        "survival_probability",
        "official_airdrop_statement",
        "official_points_future_value",
        "community_allocation",
        "distribution_catalyst_3_6m",
        "participation_open",
        "hard_cost_usd",
        "eligibility_mechanism",
        "multiwallet_policy",
    }:
        resolution = resolve_factor(current, factor_key, now)
        if resolution.record is not None:
            resolved[factor_key] = (resolution.record, resolution.value)
    return resolved


def _derive_event(
    normalized: dict[str, tuple[EvidenceRecord, Any]],
) -> ProbabilityRange | None:
    distribution = _official_true(normalized.get("official_airdrop_statement")) or _official_true(
        normalized.get("community_allocation")
    )
    if distribution and _official_true(normalized.get("distribution_catalyst_3_6m")):
        return EVENT_RULES["official_distribution_and_catalyst"]
    if distribution:
        return EVENT_RULES["official_distribution"]
    if _official_true(normalized.get("official_points_future_value")):
        return EVENT_RULES["official_points_value"]
    return None


def _derive_eligibility(
    normalized: dict[str, tuple[EvidenceRecord, Any]],
    profile: OpportunityProfile,
) -> ProbabilityRange | None:
    participation = normalized.get("participation_open")
    if participation is None or not _approved(participation, minimum_grade="B") or participation[1] is not True:
        return None
    cost_item = normalized.get("hard_cost_usd")
    mechanism_item = normalized.get("eligibility_mechanism")
    if (
        cost_item is None
        or mechanism_item is None
        or not _approved(cost_item, minimum_grade="B")
        or not _approved(mechanism_item, minimum_grade="B")
    ):
        return None
    cost = cost_item[1]
    if cost.base > profile.hard_cost_limit_per_wallet_usd:
        return None
    mechanism_keys = {
        "deterministic": "deterministic_open_within_budget",
        "points_based": "points_open_within_budget",
        "behavioral": "behavioral_open_within_budget",
    }
    rule_key = mechanism_keys.get(mechanism_item[1])
    return ELIGIBILITY_RULES.get(rule_key) if rule_key is not None else None


def _official_true(item: tuple[EvidenceRecord, Any] | None) -> bool:
    if item is None or not _approved(item, minimum_grade="A"):
        return False
    return item[1] is True


def _explicit_range(
    item: tuple[EvidenceRecord, Any] | None,
) -> ProbabilityRange | None:
    # 显式概率证据须满足与规则派生同一档的来源等级下限（B），
    # 否则 U 档（权重 0）证据也能覆盖 A 档规则结论，形成信任绕过。
    if item is None or not _approved(item, minimum_grade="B"):
        return None
    value = item[1]
    return value if isinstance(value, ProbabilityRange) else None


def _approved(
    item: tuple[EvidenceRecord, Any] | None,
    *,
    minimum_grade: str | None = None,
) -> bool:
    if item is None or item[0].observation_type not in {"observed", "derived"}:
        return False
    return minimum_grade is None or SOURCE_GRADE_WEIGHT[item[0].source_grade] >= SOURCE_GRADE_WEIGHT[minimum_grade]
