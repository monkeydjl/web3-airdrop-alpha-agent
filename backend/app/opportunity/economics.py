from math import isfinite

from app.opportunity.models import (
    EconomicsResult,
    MoneyRange,
    ProbabilityRange,
    SignedMoneyRange,
)


def calculate_economics(
    *,
    reward_probability: ProbabilityRange,
    conditional_reward: MoneyRange,
    hard_cost: MoneyRange,
    capital_loss: MoneyRange,
    liquidity_cost: MoneyRange,
    total_time_hours: MoneyRange,
    capital_at_risk_base: float = 0.0,
) -> EconomicsResult:
    if not isfinite(capital_at_risk_base):
        raise ValueError("capital_at_risk_base must be finite")
    if capital_at_risk_base < 0:
        raise ValueError("capital_at_risk_base must be non-negative")

    gross = MoneyRange(
        low=reward_probability.low * conditional_reward.low,
        base=reward_probability.base * conditional_reward.base,
        high=reward_probability.high * conditional_reward.high,
    )
    net = SignedMoneyRange(
        low=gross.low - hard_cost.high - capital_loss.high - liquidity_cost.high,
        base=gross.base - hard_cost.base - capital_loss.base - liquidity_cost.base,
        high=gross.high - hard_cost.low - capital_loss.low - liquidity_cost.low,
    )
    decision_value = 0.5 * net.low + 0.4 * net.base + 0.1 * net.high

    return EconomicsResult(
        gross_reward=gross,
        net_reward=net,
        reward_to_cost_ratio=gross.base / max(hard_cost.base, 1.0),
        decision_value=decision_value,
        capital_efficiency=decision_value / max(hard_cost.base + capital_at_risk_base, 1.0),
        time_efficiency=decision_value / max(total_time_hours.base, 0.25),
    )


def calculate_economics_if_reward_known(
    *,
    reward_probability: ProbabilityRange,
    conditional_reward: MoneyRange | None,
    hard_cost: MoneyRange,
    capital_loss: MoneyRange,
    liquidity_cost: MoneyRange,
    total_time_hours: MoneyRange,
    capital_at_risk_base: float = 0.0,
) -> EconomicsResult | None:
    if conditional_reward is None:
        return None
    return calculate_economics(
        reward_probability=reward_probability,
        conditional_reward=conditional_reward,
        hard_cost=hard_cost,
        capital_loss=capital_loss,
        liquidity_cost=liquidity_cost,
        total_time_hours=total_time_hours,
        capital_at_risk_base=capital_at_risk_base,
    )
