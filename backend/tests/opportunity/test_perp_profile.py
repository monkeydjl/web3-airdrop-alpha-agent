"""Perp-tolerant profile: relaxed cost limit, net value still decides (RED)."""

from datetime import UTC, datetime

from app.opportunity.decision import decide
from app.opportunity.models import (
    ConfidenceSet,
    EconomicsResult,
    MoneyRange,
    OpportunityInputs,
    ProbabilityRange,
    RiskLevel,
    RiskSet,
    SignedMoneyRange,
)
from app.opportunity.profile import DEFAULT_PROFILE, PERP_TOLERANT_PROFILE

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _confidence():
    return ConfidenceSet(
        event=0.80,
        eligibility=0.75,
        reward=0.70,
        cost=0.80,
        risk=0.80,
        quality=0.75,
        overall=0.75,
    )


def _risks():
    return RiskSet(
        capital_security=RiskLevel.LOW,
        eligibility=RiskLevel.LOW,
        project_failure=RiskLevel.LOW,
        reward_dilution=RiskLevel.MEDIUM,
        liquidity=RiskLevel.LOW,
    )


def _inputs(**updates):
    values = {
        "project_id": "perp-1",
        "conditional_reward_usd": MoneyRange(low=80, base=160, high=400),
        "hard_cost_usd": MoneyRange(low=30, base=35, high=45),
        "capital_at_risk_usd": MoneyRange(low=0, base=0, high=0),
        "expected_capital_loss_usd": MoneyRange(low=0, base=0, high=1),
        "liquidity_cost_usd": MoneyRange(low=0, base=0, high=1),
        "total_time_hours": MoneyRange(low=1, base=2, high=3),
        "weekly_maintenance_hours": 1.5,
        "participation_open": True,
        "task_path_known": True,
        "authorization_exit_known": True,
        "distribution_catalyst_3_6m": True,
        "project_active": True,
        "opportunity_timing": "open",
        "profile_fit": "fit",
        "weekly_time_confirmed_minimum": False,
        "hard_cost_confirmed_minimum": True,
        "integrity_blocked": False,
        "safety_blocked": False,
        "project_quality": 70,
        "project_failure_risk": RiskLevel.LOW,
        "capital_security_risk": RiskLevel.LOW,
        "official_multiwallet_policy": "allowed",
        "official_airdrop_evidence_count_a": 1,
        "independent_airdrop_evidence_count_b": 0,
        "confidence": _confidence(),
        "risks": _risks(),
    }
    values.update(updates)
    return OpportunityInputs(**values)


def _probs():
    event = ProbabilityRange(low=0.60, base=0.70, high=0.80)
    eligibility = ProbabilityRange(low=0.55, base=0.70, high=0.85)
    survival = ProbabilityRange(low=0.70, base=0.80, high=0.90)
    reward_probability = ProbabilityRange(low=0.25, base=0.39, high=0.61)
    return event, eligibility, survival, reward_probability


def _economics(**updates):
    values = {
        "gross_reward": MoneyRange(low=50, base=100, high=200),
        "net_reward": SignedMoneyRange(low=20, base=60, high=180),
        "reward_to_cost_ratio": 5,
        "decision_value": 52,
        "capital_efficiency": 5.2,
        "time_efficiency": 26,
    }
    values.update(updates)
    return EconomicsResult(**values)


def test_perp_profile_relaxes_cost_limit():
    assert PERP_TOLERANT_PROFILE.profile_id == "perp-tolerant-v1"
    assert PERP_TOLERANT_PROFILE.hard_cost_limit_per_wallet_usd == 50
    assert PERP_TOLERANT_PROFILE.weekly_time_limit_hours == 2
    assert PERP_TOLERANT_PROFILE.horizon_months == (3, 6)


def test_same_cost_rejected_by_default_profile_but_actionable_for_perp():
    event, eligibility, survival, reward_probability = _probs()
    economics = _economics()
    inputs = _inputs()

    default_decision = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=DEFAULT_PROFILE,
        now=NOW,
    )
    assert default_decision.public_label == "IGNORE"
    assert "TOO_EXPENSIVE" in default_decision.ignore_reason_codes

    perp_decision = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=PERP_TOLERANT_PROFILE,
        now=NOW,
    )
    assert perp_decision.public_label == "FARM"


def test_perp_profile_still_rejects_negative_net_value():
    event, eligibility, survival, reward_probability = _probs()
    economics = _economics(net_reward=SignedMoneyRange(low=-50, base=-10, high=20))
    inputs = _inputs()
    decision = decide(
        inputs=inputs,
        event=event,
        eligibility=eligibility,
        survival=survival,
        reward_probability=reward_probability,
        economics=economics,
        profile=PERP_TOLERANT_PROFILE,
        now=NOW,
    )
    assert decision.public_label == "IGNORE"
    assert "NEGATIVE_EXPECTED_VALUE" in decision.ignore_reason_codes
