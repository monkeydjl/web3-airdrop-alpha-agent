import math

import pytest

from app.opportunity.models import ConfidenceSet, QualityFactors
from app.opportunity.quality import (
    QUALITY_WEIGHTS,
    calculate_domain_confidence,
    calculate_overall_confidence,
    calculate_project_quality,
    with_overall_confidence,
)


def _confidence(**overrides):
    values = {
        "event": 0.8,
        "eligibility": 0.75,
        "reward": 0.4,
        "cost": 0.9,
        "risk": 0.8,
        "quality": 0.7,
    }
    values.update(overrides)
    return ConfidenceSet(**values)


def test_project_quality_uses_exact_dimension_weights():
    factors = QualityFactors(
        product_demand=100,
        execution_growth=80,
        team_governance=60,
        financial_sustainability=40,
        security_transparency=20,
    )

    assert QUALITY_WEIGHTS == {
        "product_demand": 0.25,
        "execution_growth": 0.25,
        "team_governance": 0.20,
        "financial_sustainability": 0.15,
        "security_transparency": 0.15,
    }
    assert calculate_project_quality(factors) == pytest.approx(66)


@pytest.mark.parametrize(
    "missing_dimension",
    [
        "product_demand",
        "execution_growth",
        "team_governance",
        "financial_sustainability",
        "security_transparency",
    ],
)
def test_any_missing_quality_dimension_returns_none(missing_dimension):
    values = {
        "product_demand": 50,
        "execution_growth": 50,
        "team_governance": 50,
        "financial_sustainability": 50,
        "security_transparency": 50,
    }
    values[missing_dimension] = None

    assert calculate_project_quality(QualityFactors(**values)) is None


def test_quality_boundary_values_remain_valid_and_weighted():
    factors = QualityFactors(
        product_demand=0,
        execution_growth=100,
        team_governance=0,
        financial_sustainability=100,
        security_transparency=0,
    )

    assert calculate_project_quality(factors) == pytest.approx(40)


def test_domain_confidence_uses_exact_weights():
    result = calculate_domain_confidence(
        source_reliability=0.8,
        evidence_coverage=0.6,
        source_independence=0.4,
        freshness_consistency=0.2,
    )

    assert result == pytest.approx(0.35 * 0.8 + 0.25 * 0.6 + 0.15 * 0.4 + 0.25 * 0.2)


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        ((0, 0, 0, 0), 0),
        ((1, 1, 1, 1), 1),
        ((2, 2, 2, 2), 1),
        ((-1, -1, -1, -1), 0),
    ],
)
def test_domain_confidence_clamps_to_closed_unit_interval(values, expected):
    result = calculate_domain_confidence(
        source_reliability=values[0],
        evidence_coverage=values[1],
        source_independence=values[2],
        freshness_consistency=values[3],
    )

    assert result == expected


@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_domain_confidence_rejects_non_finite_inputs(non_finite):
    with pytest.raises(ValueError, match="finite"):
        calculate_domain_confidence(
            source_reliability=non_finite,
            evidence_coverage=1,
            source_independence=1,
            freshness_consistency=1,
        )


def test_overall_confidence_penalizes_weakest_domain():
    confidence = _confidence()
    expected_average = (0.8 + 0.75 + 0.4 + 0.9 + 0.8 + 0.7) / 6

    assert calculate_overall_confidence(confidence) == pytest.approx(0.3 * 0.4 + 0.7 * expected_average)


@pytest.mark.parametrize("score", [0, 1])
def test_overall_confidence_boundary_values_are_stable(score):
    assert (
        calculate_overall_confidence(
            _confidence(**{key: score for key in ("event", "eligibility", "reward", "cost", "risk", "quality")})
        )
        == score
    )


def test_with_overall_confidence_updates_immutable_confidence_set():
    confidence = _confidence(overall=0)
    updated = with_overall_confidence(confidence)

    assert updated.overall == pytest.approx(calculate_overall_confidence(confidence))
    assert confidence.overall == 0
