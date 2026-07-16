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
    return ProbabilityRange(
        low=event.low * eligibility.low * survival.low,
        base=event.base * eligibility.base * survival.base,
        high=event.high * eligibility.high * survival.high,
    )


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
    if not _approved(participation, minimum_grade="B") or participation[1] is not True:
        return None
    cost_item = normalized.get("hard_cost_usd")
    mechanism_item = normalized.get("eligibility_mechanism")
    if not _approved(cost_item, minimum_grade="B") or not _approved(mechanism_item, minimum_grade="B"):
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
    return _approved(item, minimum_grade="A") and item[1] is True


def _explicit_range(
    item: tuple[EvidenceRecord, Any] | None,
) -> ProbabilityRange | None:
    if not _approved(item):
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
