from math import isfinite

from app.opportunity.models import ConfidenceSet, QualityFactors

QUALITY_WEIGHTS = {
    "product_demand": 0.25,
    "execution_growth": 0.25,
    "team_governance": 0.20,
    "financial_sustainability": 0.15,
    "security_transparency": 0.15,
}


def calculate_project_quality(factors: QualityFactors) -> float | None:
    values = factors.model_dump()
    if any(value is None for value in values.values()):
        return None
    return sum(values[key] * weight for key, weight in QUALITY_WEIGHTS.items())


def calculate_domain_confidence(
    *,
    source_reliability: float,
    evidence_coverage: float,
    source_independence: float,
    freshness_consistency: float,
) -> float:
    scores = (
        source_reliability,
        evidence_coverage,
        source_independence,
        freshness_consistency,
    )
    if not all(isfinite(score) for score in scores):
        raise ValueError("domain confidence inputs must be finite")
    value = (
        0.35 * source_reliability + 0.25 * evidence_coverage + 0.15 * source_independence + 0.25 * freshness_consistency
    )
    return max(0.0, min(1.0, value))


def calculate_overall_confidence(value: ConfidenceSet) -> float:
    scores = (
        value.event,
        value.eligibility,
        value.reward,
        value.cost,
        value.risk,
        value.quality,
    )
    return 0.3 * min(scores) + 0.7 * (sum(scores) / len(scores))


def with_overall_confidence(value: ConfidenceSet) -> ConfidenceSet:
    return value.model_copy(update={"overall": calculate_overall_confidence(value)})
