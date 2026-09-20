"""Tests for Anti-PUA & Capital Preservation Engine.

Covers:
- calculate_fatigue_index and get_fatigue_level
- classify_capital_friction_tier
- evaluate_exit_advisory
- decision engine integration (PUA_FATIGUE_WARNING, EXIT_RECOMMENDED, HEAVY_CAPITAL_LOCKUP)
"""

from datetime import UTC, datetime

import pytest

from app.opportunity.decision import (
    EXIT_RECOMMENDED,
    HEAVY_CAPITAL_LOCKUP,
    PUA_FATIGUE_WARNING,
    decide,
)
from app.opportunity.models import (
    ConfidenceSet,
    DecisionStatus,
    EconomicsResult,
    MoneyRange,
    OpportunityInputs,
    ProbabilityRange,
    RiskLevel,
    RiskSet,
    SignedMoneyRange,
)
from app.opportunity.profile import DEFAULT_PROFILE, OpportunityProfile
from app.services.anti_pua import (
    calculate_fatigue_index,
    classify_capital_friction_tier,
    evaluate_exit_advisory,
    get_fatigue_level,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_calculate_fatigue_index_low():
    """Short campaign, single season, clear tokenomics, no lockup."""
    score = calculate_fatigue_index(
        duration_months=2.0,
        season_count=1,
        tge_transparency="clear",
        lockup_days=0,
    )
    assert score < 0.35
    assert get_fatigue_level(score) == "low"


def test_calculate_fatigue_index_high():
    """Over a year, 4 seasons of points, zero tokenomics clarity, 180-day lockup."""
    score = calculate_fatigue_index(
        duration_months=14.0,
        season_count=4,
        tge_transparency="unannounced",
        lockup_days=180,
    )
    assert score >= 0.70
    assert get_fatigue_level(score) in ("high", "critical")


def test_calculate_fatigue_index_boundary():
    """Moderate campaign around medium level."""
    score = calculate_fatigue_index(
        duration_months=5.0,
        season_count=2,
        tge_transparency="vague_soon",
        lockup_days=15,
    )
    assert 0.35 <= score < 0.70
    assert get_fatigue_level(score) == "medium"


def test_classify_capital_friction_tier_zero_cost():
    """Pure testnet interaction, no capital, minimal gas."""
    tier = classify_capital_friction_tier(
        has_testnet=True,
        hard_cost_usd=2.0,
        capital_at_risk_usd=0.0,
    )
    assert tier == "zero_cost"


def test_classify_capital_friction_tier_low_cost():
    """Small gas fees, <$50 capital."""
    tier = classify_capital_friction_tier(
        has_testnet=False,
        hard_cost_usd=8.0,
        capital_at_risk_usd=30.0,
    )
    assert tier == "low_cost"


def test_classify_capital_friction_tier_medium_cost():
    """Moderate capital staking, e.g. $200."""
    tier = classify_capital_friction_tier(
        has_testnet=False,
        hard_cost_usd=20.0,
        capital_at_risk_usd=200.0,
    )
    assert tier == "medium_cost"


def test_classify_capital_friction_tier_heavy_capital():
    """Large capital deposit or perp volume."""
    tier_by_capital = classify_capital_friction_tier(
        has_testnet=False,
        hard_cost_usd=60.0,
        capital_at_risk_usd=1000.0,
    )
    assert tier_by_capital == "heavy_capital"

    tier_by_perp = classify_capital_friction_tier(
        has_testnet=False,
        hard_cost_usd=5.0,
        capital_at_risk_usd=10.0,
        is_perp=True,
    )
    assert tier_by_perp == "heavy_capital"


def test_evaluate_exit_advisory_tvl_drain():
    """TVL drops > 30% triggers TVL_DRAIN."""
    advisory = evaluate_exit_advisory(
        tvl_drain_ratio=0.45,
        github_inactive_days=10,
        site_alive=True,
        rule_worsened=False,
    )
    assert advisory["active"] is True
    assert "TVL_DRAIN" in advisory["reasons"]
    assert advisory["severity"] == "critical"


def test_evaluate_exit_advisory_dev_inactive():
    """Dev inactivity >= 60 days triggers DEV_INACTIVE."""
    advisory = evaluate_exit_advisory(
        tvl_drain_ratio=0.05,
        github_inactive_days=75,
        site_alive=True,
        rule_worsened=False,
    )
    assert advisory["active"] is True
    assert "DEV_INACTIVE" in advisory["reasons"]
    assert advisory["severity"] == "warning"


def test_evaluate_exit_advisory_site_offline():
    """Site offline triggers SITE_OFFLINE."""
    advisory = evaluate_exit_advisory(
        tvl_drain_ratio=0.0,
        github_inactive_days=5,
        site_alive=False,
        rule_worsened=False,
    )
    assert advisory["active"] is True
    assert "SITE_OFFLINE" in advisory["reasons"]
    assert advisory["severity"] == "critical"


def test_evaluate_exit_advisory_rule_worse():
    """Rule change worsening triggers RULE_WORSE."""
    advisory = evaluate_exit_advisory(
        tvl_drain_ratio=0.0,
        github_inactive_days=5,
        site_alive=True,
        rule_worsened=True,
    )
    assert advisory["active"] is True
    assert "RULE_WORSE" in advisory["reasons"]


def test_evaluate_exit_advisory_healthy():
    """Healthy project triggers nothing."""
    advisory = evaluate_exit_advisory(
        tvl_drain_ratio=0.05,
        github_inactive_days=5,
        site_alive=True,
        rule_worsened=False,
    )
    assert advisory["active"] is False
    assert len(advisory["reasons"]) == 0
    assert advisory["severity"] == "none"


def _make_inputs(**updates):
    values = {
        "project_id": "p-anti-pua",
        "conditional_reward_usd": MoneyRange(low=100, base=250, high=500),
        "hard_cost_usd": MoneyRange(low=2, base=5, high=10),
        "capital_at_risk_usd": MoneyRange(low=0, base=0, high=0),
        "expected_capital_loss_usd": MoneyRange(low=0, base=0, high=1),
        "liquidity_cost_usd": MoneyRange(low=0, base=0, high=1),
        "total_time_hours": MoneyRange(low=1, base=2, high=3),
        "weekly_maintenance_hours": 1.0,
        "participation_open": True,
        "task_path_known": True,
        "authorization_exit_known": True,
        "distribution_catalyst_3_6m": True,
        "project_active": True,
        "opportunity_timing": "open",
        "profile_fit": "fit",
        "weekly_time_confirmed_minimum": False,
        "integrity_blocked": False,
        "safety_blocked": False,
        "project_quality": 80,
        "project_failure_risk": RiskLevel.LOW,
        "capital_security_risk": RiskLevel.LOW,
        "official_multiwallet_policy": "allowed",
        "official_airdrop_evidence_count_a": 1,
        "independent_airdrop_evidence_count_b": 0,
        "confidence": ConfidenceSet(
            event=0.85, eligibility=0.8, reward=0.75, cost=0.8, risk=0.8, quality=0.8, overall=0.8
        ),
        "risks": RiskSet(
            capital_security=RiskLevel.LOW,
            eligibility=RiskLevel.LOW,
            project_failure=RiskLevel.LOW,
            reward_dilution=RiskLevel.LOW,
            liquidity=RiskLevel.LOW,
        ),
        "fatigue_index": 0.2,
        "capital_friction_tier": "zero_cost",
        "exit_advisory": {"active": False},
    }
    values.update(updates)
    return OpportunityInputs(**values)


def _make_economics(**updates):
    values = {
        "gross_reward": MoneyRange(low=100, base=250, high=500),
        "net_reward": SignedMoneyRange(low=80, base=240, high=480),
        "reward_to_cost_ratio": 25.0,
        "decision_value": 200.0,
        "capital_efficiency": 10.0,
        "time_efficiency": 50.0,
    }
    values.update(updates)
    return EconomicsResult(**values)


def test_decision_downgrades_on_high_fatigue():
    """A project that would otherwise be ACTIONABLE is downgraded to WATCH when fatigue_index >= 0.70."""
    inputs = _make_inputs(fatigue_index=0.78)
    econ = _make_economics()
    res = decide(
        inputs=inputs,
        event=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        eligibility=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        survival=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        reward_probability=ProbabilityRange(low=0.5, base=0.6, high=0.7),
        economics=econ,
        profile=DEFAULT_PROFILE,
        now=NOW,
    )

    assert res.status == DecisionStatus.MONITOR
    assert res.public_label == "WATCH"
    assert PUA_FATIGUE_WARNING in res.watch_reason_codes
    assert res.fatigue_index == 0.78


def test_decision_triggers_exit_recommended():
    """A project with exit advisory active triggers EXIT_RECOMMENDED and not_fit."""
    inputs = _make_inputs(
        exit_advisory={
            "active": True,
            "reasons": ("TVL_DRAIN",),
            "reasons_zh": ("30 天内 TVL 持续大额净流出 (>30%)",),
        }
    )
    econ = _make_economics()
    res = decide(
        inputs=inputs,
        event=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        eligibility=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        survival=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        reward_probability=ProbabilityRange(low=0.5, base=0.6, high=0.7),
        economics=econ,
        profile=DEFAULT_PROFILE,
        now=NOW,
    )

    assert res.status == DecisionStatus.NOT_FIT
    assert res.public_label == "IGNORE"
    assert EXIT_RECOMMENDED in res.ignore_reason_codes
    assert res.exit_advisory is not None
    assert res.exit_advisory["active"] is True


def test_decision_flags_heavy_capital_lockup():
    """A project with heavy capital friction tier gets HEAVY_CAPITAL_LOCKUP reason when exceeding profile budget."""
    inputs = _make_inputs(
        capital_friction_tier="heavy_capital",
        capital_at_risk_usd=MoneyRange(low=1500, base=2000, high=3000),
    )
    econ = _make_economics()
    res = decide(
        inputs=inputs,
        event=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        eligibility=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        survival=ProbabilityRange(low=0.7, base=0.8, high=0.9),
        reward_probability=ProbabilityRange(low=0.5, base=0.6, high=0.7),
        economics=econ,
        profile=DEFAULT_PROFILE,
        now=NOW,
    )

    assert res.status == DecisionStatus.NOT_FIT
    assert res.public_label == "IGNORE"
    assert HEAVY_CAPITAL_LOCKUP in res.ignore_reason_codes
    assert res.capital_friction_tier == "heavy_capital"
