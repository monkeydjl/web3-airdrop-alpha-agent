import math
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest

from app.opportunity.calibration import (
    CalibrationSample,
    RangeValue,
    map_outcomes,
    maturity_state,
)


def sample(**updates):
    values = {
        "project_id": "project-1",
        "assessment_id": "assessment-1",
        "cohort_id": "cohort-550e8400-e29b-41d4-a716-446655440000",
        "scored_at": datetime(2026, 1, 1, tzinfo=UTC),
        "outcome_observed_at": datetime(2026, 4, 1, tzinfo=UTC),
        "model_version": "opportunity-v2.0",
        "profile_version": "low-cost-curated-multiwallet-v1",
        "status": "ACTIONABLE",
        "public_label": "FARM",
        "wallet_count": 3,
        "event_probability": RangeValue(0.6, 0.7, 0.8),
        "eligibility_probability": RangeValue(0.5, 0.6, 0.7),
        "survival_probability": RangeValue(0.7, 0.8, 0.9),
        "reward_probability": RangeValue(0.3, 0.4, 0.5),
        "net_reward": RangeValue(10, 30, 50),
        "hard_cost": RangeValue(2, 4, 6),
        "total_time_hours": RangeValue(1, 2, 3),
        "outcome": "airdropped",
        "eligibility_result": "eligible",
        "survival_result": "passed",
        "reward_received_usd": 40.0,
        "actual_hard_cost_usd": 5.0,
        "claim_cost_usd": 1.0,
        "actual_time_minutes": 150,
    }
    return CalibrationSample(**(values | updates))


def test_range_value_is_immutable():
    value = RangeValue(0.1, 0.2, 0.3)

    with pytest.raises(FrozenInstanceError):
        value.base = 0.4


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_range_value_rejects_non_finite_values(value):
    with pytest.raises(ValueError):
        RangeValue(value, value, value)


@pytest.mark.parametrize(
    "values",
    [(0.2, 0.1, 0.3), (0.1, 0.3, 0.2)],
)
def test_range_value_requires_ordered_values(values):
    with pytest.raises(ValueError):
        RangeValue(*values)


def test_calibration_sample_is_immutable():
    value = sample()

    with pytest.raises(FrozenInstanceError):
        value.status = "WATCH"


def test_maturity_is_immature_at_89_days():
    value = sample(outcome_observed_at=datetime(2026, 3, 31, tzinfo=UTC))

    assert (
        maturity_state(
            value,
            as_of=value.outcome_observed_at,
            window_days=90,
        )
        == "immature"
    )


def test_maturity_is_mature_at_90_days():
    value = sample()

    assert (
        maturity_state(
            value,
            as_of=value.outcome_observed_at,
            window_days=90,
        )
        == "mature"
    )


def test_maturity_rejects_future_outcome():
    value = sample()

    assert (
        maturity_state(
            value,
            as_of=value.outcome_observed_at - timedelta(seconds=1),
            window_days=90,
        )
        == "outcome_after_as_of"
    )


def test_maturity_rejects_outcome_before_scoring():
    value = sample(outcome_observed_at=datetime(2025, 12, 31, tzinfo=UTC))

    assert (
        maturity_state(
            value,
            as_of=datetime(2026, 4, 1, tzinfo=UTC),
            window_days=90,
        )
        == "outcome_before_assessment"
    )


@pytest.mark.parametrize(
    ("updates", "field", "expected"),
    [
        ({"outcome": "airdropped"}, "event", 1),
        ({"outcome": "not_airdropped", "reward_received_usd": 0}, "event", 0),
        ({"outcome": "profit"}, "event", None),
        ({"eligibility_result": "eligible"}, "eligibility", 1),
        ({"eligibility_result": "ineligible", "reward_received_usd": 0}, "eligibility", 0),
        ({"survival_result": "passed"}, "survival", 1),
        ({"survival_result": "disqualified", "reward_received_usd": 0}, "survival", 0),
        ({"reward_received_usd": 40}, "reward", 1),
        ({"reward_received_usd": 0}, "reward", 0),
        ({"reward_received_usd": None}, "reward", None),
    ],
)
def test_maps_outcome_dimensions(updates, field, expected):
    values, concerns = map_outcomes(sample(**updates))

    assert getattr(values, field) == expected
    assert concerns == ()


@pytest.mark.parametrize(
    "updates",
    [
        {"eligibility_result": "ineligible"},
        {"survival_result": "disqualified"},
        {"outcome": "not_airdropped"},
    ],
)
def test_contradictory_positive_reward_suppresses_economic_outcomes(updates):
    values, concerns = map_outcomes(sample(**updates))

    assert values.reward is None
    assert values.realized_net_usd is None
    assert values.realized_class is None
    assert concerns == ("contradictory_outcome",)


@pytest.mark.parametrize(
    "updates",
    [
        {"reward_received_usd": None},
        {"actual_hard_cost_usd": None},
        {"claim_cost_usd": None},
    ],
)
def test_economic_outcomes_require_reward_and_both_costs(updates):
    values, concerns = map_outcomes(sample(**updates))

    assert values.realized_net_usd is None
    assert values.realized_class is None
    assert concerns == ()


@pytest.mark.parametrize(
    ("reward", "hard_cost", "claim_cost", "net", "realized_class"),
    [
        (40.0, 5.0, 1.0, 34.0, "POSITIVE"),
        (4.0, 5.0, 1.0, -2.0, "NEGATIVE"),
        (6.0, 5.0, 1.0, 0.0, "NEUTRAL"),
    ],
)
def test_maps_realized_net_and_class(
    reward,
    hard_cost,
    claim_cost,
    net,
    realized_class,
):
    values, concerns = map_outcomes(
        sample(
            reward_received_usd=reward,
            actual_hard_cost_usd=hard_cost,
            claim_cost_usd=claim_cost,
        )
    )

    assert values.realized_net_usd == net
    assert values.realized_class == realized_class
    assert concerns == ()


def test_maps_actual_time_to_hours():
    values, _ = map_outcomes(sample(actual_time_minutes=150))

    assert values.actual_time_hours == 2.5
