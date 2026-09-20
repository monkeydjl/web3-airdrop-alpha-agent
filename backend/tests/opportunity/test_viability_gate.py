"""Tests for Runway & Viability Gate.

Covers:
- evaluate_project_viability:
  - UNBACKED_POINTS_MACHINE (zero funding points programs)
  - LOW_FUNDING_UNVIABLE (< $3M without tier-1/tier-2 investors)
  - RUNWAY_DEPLETED (> 18 months since small round + stale dev / tvl drain)
  - Borderline conditions ($3M - $6M)
  - Healthy viable conditions
- decision engine integration:
  - Unbacked points machine -> IGNORE (NOT_FIT)
  - Low funding / depleted runway -> WATCH (MONITOR)
"""

from datetime import UTC, datetime, timedelta

import pytest

from app.opportunity.decision import (
    LOW_RUNWAY_RISK,
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
from app.opportunity.profile import DEFAULT_PROFILE
from app.services.viability_gate import (
    LOW_FUNDING_UNVIABLE,
    RUNWAY_DEPLETED,
    UNBACKED_POINTS_MACHINE,
    evaluate_project_viability,
)

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def test_viability_unbacked_points_machine():
    """Points program running with zero funding and no tier-1 VC backing is unviable."""
    res = evaluate_project_viability(
        funding_total_usd=0,
        funding_investors=[],
        has_points_program=True,
        now=NOW,
    )
    assert res["tier"] == "unviable"
    assert UNBACKED_POINTS_MACHINE in res["reasons"]
    assert len(res["reasons_zh"]) > 0
    assert "零融资" in res["reasons_zh"][0]


def test_viability_low_funding_unviable():
    """Public funding < $3M with no tier-1/tier-2 investors is flagged as unviable."""
    res = evaluate_project_viability(
        funding_total_usd=1_500_000,
        funding_investors=["Some Unknown Angel"],
        has_points_program=False,
        now=NOW,
    )
    assert res["tier"] == "unviable"
    assert LOW_FUNDING_UNVIABLE in res["reasons"]
    assert "公开融资 < $3M" in res["reasons_zh"][0]


def test_viability_tier1_vc_passes_low_funding():
    """Projects with < $3M but backed by Tier-1 VCs (e.g. Paradigm, a16z) pass the gate."""
    res = evaluate_project_viability(
        funding_total_usd=2_000_000,
        funding_investors=["Paradigm", "Robot Ventures"],
        has_points_program=False,
        now=NOW,
    )
    assert LOW_FUNDING_UNVIABLE not in res["reasons"]
    assert res["tier"] != "unviable"


def test_viability_runway_depleted():
    """Small funding > 18 months ago combined with stale dev triggers RUNWAY_DEPLETED."""
    last_date = (NOW - timedelta(days=600)).strftime("%Y-%m-%d")
    res = evaluate_project_viability(
        funding_total_usd=4_000_000,
        funding_last_date=last_date,
        github_inactive_days=120,
        now=NOW,
    )
    assert res["tier"] == "unviable"
    assert RUNWAY_DEPLETED in res["reasons"]
    assert "跑道资金基本耗尽" in res["reasons_zh"][0]


def test_viability_borderline():
    """Funding between $3M and $6M without top-tier VC is borderline."""
    res = evaluate_project_viability(
        funding_total_usd=4_500_000,
        funding_investors=["Random Fund"],
        github_inactive_days=10,
        now=NOW,
    )
    assert res["tier"] == "borderline"
    assert len(res["reasons"]) == 0
    assert "相对偏紧" in res["recommendation_zh"]


def test_viability_healthy():
    """Large funding and reputable investors result in viable tier."""
    last_date = (NOW - timedelta(days=90)).strftime("%Y-%m-%d")
    res = evaluate_project_viability(
        funding_total_usd=20_000_000,
        funding_investors=["a16z crypto", "Polychain Capital"],
        funding_last_date=last_date,
        github_inactive_days=5,
        now=NOW,
    )
    assert res["tier"] == "viable"
    assert len(res["reasons"]) == 0
    assert "相对稳健" in res["recommendation_zh"]


def _make_inputs(**updates):
    values = {
        "project_id": "p-viability-test",
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
        "viability_tier": "viable",
        "viability_advisory": {"tier": "viable", "reasons": []},
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


def test_decision_blocks_unbacked_points_machine_to_ignore():
    """An otherwise actionable project is dropped to IGNORE (NOT_FIT) if it's an unbacked points machine."""
    inputs = _make_inputs(
        viability_tier="unviable",
        viability_advisory={
            "tier": "unviable",
            "reasons": [UNBACKED_POINTS_MACHINE],
            "recommendation_zh": "拦截",
        },
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
    assert LOW_RUNWAY_RISK in res.ignore_reason_codes


def test_decision_downgrades_low_funding_to_watch():
    """An otherwise actionable project is downgraded to WATCH (MONITOR) if low funding unviable."""
    inputs = _make_inputs(
        viability_tier="unviable",
        viability_advisory={
            "tier": "unviable",
            "reasons": [LOW_FUNDING_UNVIABLE],
            "recommendation_zh": "降级观察",
        },
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
    assert res.status == DecisionStatus.MONITOR
    assert res.public_label == "WATCH"
    assert LOW_RUNWAY_RISK in res.watch_reason_codes
