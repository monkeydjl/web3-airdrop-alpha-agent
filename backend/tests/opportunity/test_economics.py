import math
from typing import get_type_hints

import pytest

from app.opportunity.economics import (
    calculate_economics,
    calculate_economics_if_reward_known,
)
from app.opportunity.models import EconomicsResult, MoneyRange, ProbabilityRange


def _economics(**overrides):
    values = {
        "reward_probability": ProbabilityRange(low=0.25, base=0.365, high=0.51),
        "conditional_reward": MoneyRange(low=40, base=160, high=500),
        "hard_cost": MoneyRange(low=3, base=3, high=3),
        "capital_loss": MoneyRange(low=0, base=0, high=0),
        "liquidity_cost": MoneyRange(low=0, base=0, high=0),
        "total_time_hours": MoneyRange(low=1, base=1.2, high=2),
    }
    values.update(overrides)
    return calculate_economics(**values)


def test_economics_matches_scenarios_and_uses_conservative_decision_weights():
    result = _economics()

    assert result.gross_reward.model_dump() == pytest.approx({"low": 10, "base": 58.4, "high": 255})
    assert result.net_reward.model_dump() == pytest.approx({"low": 7, "base": 55.4, "high": 252})
    assert result.decision_value == pytest.approx(50.86)
    assert result.time_efficiency == pytest.approx(50.86 / 1.2)


def test_conservative_net_subtracts_high_cost_loss_and_liquidity():
    result = _economics(
        hard_cost=MoneyRange(low=1, base=2, high=3),
        capital_loss=MoneyRange(low=4, base=5, high=6),
        liquidity_cost=MoneyRange(low=7, base=8, high=9),
    )

    assert result.net_reward.low == pytest.approx(10 - 3 - 6 - 9)
    assert result.net_reward.base == pytest.approx(58.4 - 2 - 5 - 8)
    assert result.net_reward.high == pytest.approx(255 - 1 - 4 - 7)


def test_negative_net_reward_is_preserved_without_clamping():
    result = _economics(hard_cost=MoneyRange(low=20, base=20, high=20))

    assert result.net_reward.low == pytest.approx(-10)
    assert result.decision_value == pytest.approx(
        0.5 * result.net_reward.low + 0.4 * result.net_reward.base + 0.1 * result.net_reward.high
    )


def test_reward_to_cost_uses_base_gross_and_one_dollar_floor():
    result = _economics(hard_cost=MoneyRange(low=0, base=0, high=0))

    assert result.reward_to_cost_ratio == pytest.approx(58.4)


def test_capital_efficiency_includes_base_capital_at_risk():
    result = _economics(capital_at_risk_base=40)

    assert result.capital_efficiency == pytest.approx(result.decision_value / 43)


@pytest.mark.parametrize("base_hours", [0, 0.24, 0.25])
def test_time_efficiency_uses_quarter_hour_minimum(base_hours):
    result = _economics(total_time_hours=MoneyRange(low=0, base=base_hours, high=0.25))

    assert result.time_efficiency == pytest.approx(result.decision_value / 0.25)


def test_missing_conditional_reward_returns_none_through_typed_helper():
    result = calculate_economics_if_reward_known(
        reward_probability=ProbabilityRange(low=0.2, base=0.4, high=0.6),
        conditional_reward=None,
        hard_cost=MoneyRange(low=0, base=1, high=2),
        capital_loss=MoneyRange(low=0, base=0, high=0),
        liquidity_cost=MoneyRange(low=0, base=0, high=0),
        total_time_hours=MoneyRange(low=0, base=1, high=2),
    )

    assert result is None
    assert get_type_hints(calculate_economics_if_reward_known)["return"] == (EconomicsResult | None)
    assert get_type_hints(calculate_economics)["conditional_reward"] is MoneyRange


@pytest.mark.parametrize("capital_at_risk_base", [math.nan, math.inf, -math.inf])
def test_capital_at_risk_base_must_be_finite(capital_at_risk_base):
    with pytest.raises(ValueError, match="finite"):
        _economics(capital_at_risk_base=capital_at_risk_base)


def test_capital_at_risk_base_cannot_be_negative():
    with pytest.raises(ValueError, match="non-negative"):
        _economics(capital_at_risk_base=-0.01)
