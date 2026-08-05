from datetime import UTC, datetime, timedelta
from inspect import signature

import pytest

from app.opportunity.decision import (
    BLOCK_REASON_ACTIONS,
    IGNORE_REASON_ACTIONS,
    WATCH_REASON_ACTIONS,
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

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _confidence(**updates):
    values = {
        "event": 0.80,
        "eligibility": 0.75,
        "reward": 0.70,
        "cost": 0.80,
        "risk": 0.80,
        "quality": 0.75,
        "overall": 0.75,
    }
    values.update(updates)
    return ConfidenceSet(**values)


def _risks(**updates):
    values = {
        "capital_security": RiskLevel.LOW,
        "eligibility": RiskLevel.LOW,
        "project_failure": RiskLevel.LOW,
        "reward_dilution": RiskLevel.MEDIUM,
        "liquidity": RiskLevel.LOW,
    }
    values.update(updates)
    return RiskSet(**values)


def _economics(**updates):
    values = {
        "gross_reward": MoneyRange(low=50, base=100, high=200),
        "net_reward": SignedMoneyRange(low=20, base=60, high=180),
        "reward_to_cost_ratio": 10,
        "decision_value": 52,
        "capital_efficiency": 5.2,
        "time_efficiency": 26,
    }
    values.update(updates)
    return EconomicsResult(**values)


def _inputs(**updates):
    values = {
        "project_id": "p1",
        "conditional_reward_usd": MoneyRange(low=80, base=160, high=400),
        "hard_cost_usd": MoneyRange(low=5, base=8, high=10),
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


@pytest.fixture
def passing_case():
    return {
        "inputs": _inputs(),
        "event": ProbabilityRange(low=0.60, base=0.70, high=0.80),
        "eligibility": ProbabilityRange(low=0.55, base=0.70, high=0.85),
        "survival": ProbabilityRange(low=0.70, base=0.80, high=0.90),
        "reward_probability": ProbabilityRange(low=0.25, base=0.39, high=0.61),
        "economics": _economics(),
        "profile": DEFAULT_PROFILE,
        "now": NOW,
    }


def _with_input(case, **updates):
    return {**case, "inputs": case["inputs"].model_copy(update=updates)}


def test_decide_has_exact_keyword_only_signature():
    parameters = signature(decide).parameters
    assert tuple(parameters) == (
        "inputs",
        "event",
        "eligibility",
        "survival",
        "reward_probability",
        "economics",
        "profile",
        "now",
    )
    assert all(parameter.kind.name == "KEYWORD_ONLY" for parameter in parameters.values())


def test_complete_profitable_safe_project_is_actionable(passing_case):
    result = decide(**passing_case)
    assert result.status == DecisionStatus.ACTIONABLE
    assert result.public_label == "FARM"
    assert result.recommended_action == (
        "Run 1-2 wallets, record actual cost and time, then reassess before expanding."
    )
    assert result.review_at == NOW + timedelta(hours=48)
    assert result.expires_at == NOW + timedelta(hours=48)
    assert result.requires_remediation is False


def test_hard_cost_uses_worst_reasonable_high_envelope(passing_case):
    monitor = decide(
        **_with_input(
            passing_case,
            hard_cost_usd=MoneyRange(low=5, base=9, high=10.01),
        )
    )
    structural = decide(
        **_with_input(
            passing_case,
            hard_cost_usd=MoneyRange(low=10.01, base=11, high=12),
        )
    )

    assert monitor.status == DecisionStatus.MONITOR
    assert monitor.watch_reason_codes == ("WAIT_COST_DROP",)
    assert structural.status == DecisionStatus.NOT_FIT
    assert structural.ignore_reason_codes == ("TOO_EXPENSIVE",)


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"safety_blocked": True}, "SAFETY_BLOCK"),
        ({"capital_security_risk": RiskLevel.CRITICAL}, "SAFETY_BLOCK"),
        ({"integrity_blocked": True}, "INTEGRITY_BLOCK"),
        ({"official_multiwallet_policy": "forbidden"}, "RULE_BLOCK"),
    ],
)
def test_hard_blockers_cannot_be_compensated(passing_case, updates, code):
    result = decide(**_with_input(passing_case, **updates))
    assert result.status == DecisionStatus.BLOCKED
    assert result.public_label == "IGNORE"
    assert result.blocker_codes == (code,)
    assert result.review_at == NOW + timedelta(days=30)
    assert result.expires_at == NOW + timedelta(days=30)
    assert result.requires_remediation is True


def test_blocker_precedence_is_safety_then_integrity_then_rule(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            safety_blocked=True,
            integrity_blocked=True,
            official_multiwallet_policy="forbidden",
        )
    )
    assert result.blocker_codes == ("SAFETY_BLOCK",)


@pytest.mark.parametrize(
    ("top_level", "nested"),
    [
        (RiskLevel.LOW, RiskLevel.CRITICAL),
        (RiskLevel.CRITICAL, RiskLevel.LOW),
    ],
)
def test_any_critical_capital_security_representation_blocks(passing_case, top_level, nested):
    result = decide(
        **_with_input(
            passing_case,
            capital_security_risk=top_level,
            risks=_risks(capital_security=nested),
        )
    )
    assert result.status == DecisionStatus.BLOCKED
    assert result.blocker_codes == ("SAFETY_BLOCK",)
    assert result.requires_remediation is True


def test_conflicting_high_capital_security_uses_safest_interpretation(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            capital_security_risk=RiskLevel.LOW,
            risks=_risks(capital_security=RiskLevel.HIGH),
        )
    )
    assert result.status == DecisionStatus.MONITOR
    assert "WAIT_MORE_EVIDENCE" in result.watch_reason_codes


def test_missing_capital_security_is_insufficient(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            capital_security_risk=None,
            risks=_risks(capital_security=None),
        )
    )
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE


def test_nested_high_project_failure_uses_safest_interpretation(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            project_failure_risk=RiskLevel.LOW,
            risks=_risks(project_failure=RiskLevel.HIGH),
        )
    )
    assert result.status == DecisionStatus.MONITOR
    assert "WAIT_MORE_EVIDENCE" in result.watch_reason_codes


def test_missing_project_failure_in_both_representations_is_insufficient(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            project_failure_risk=None,
            risks=_risks(project_failure=None),
        )
    )
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE


def test_critical_unknowns_precede_numeric_gates(passing_case):
    case = _with_input(passing_case, critical_unknowns=("hard_cost",))
    case["event"] = ProbabilityRange(low=0, base=0, high=0)
    result = decide(**case)
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"
    assert result.watch_reason_codes == ("WAIT_MORE_EVIDENCE",)


@pytest.mark.parametrize(
    ("unknown", "code"),
    [
        ("participation_open", "WAIT_TASK_OPEN"),
        ("multiwallet_policy", "WAIT_RULES"),
        ("distribution_catalyst_3_6m", "WAIT_CATALYST"),
        ("conditional_reward", "REWARD_TOO_UNCERTAIN"),
        ("official_identity", "WAIT_MORE_EVIDENCE"),
        # service.evaluate_row 注入的是模型字段名（带 _usd/_hours 后缀）。此前这套
        # 命名一个都不在映射表里，8 个缺失事实全部塌缩成通用码 WAIT_MORE_EVIDENCE。
        ("reward_probability", "REWARD_TOO_UNCERTAIN"),
        ("conditional_reward_usd", "REWARD_TOO_UNCERTAIN"),
        ("hard_cost_usd", "WAIT_MORE_EVIDENCE"),
        ("capital_at_risk_usd", "WAIT_MORE_EVIDENCE"),
        ("expected_capital_loss_usd", "WAIT_MORE_EVIDENCE"),
        ("liquidity_cost_usd", "WAIT_MORE_EVIDENCE"),
        ("total_time_hours", "WAIT_MORE_EVIDENCE"),
        ("economics_direct_evidence", "WAIT_MORE_EVIDENCE"),
    ],
)
def test_critical_unknown_mapping_is_deterministic(passing_case, unknown, code):
    result = decide(**_with_input(passing_case, critical_unknowns=(unknown, unknown)))
    assert result.watch_reason_codes == (code,)


def test_both_naming_schemes_for_one_missing_fact_yield_one_reason_code():
    """conditional_reward 与 conditional_reward_usd 指同一件缺失事实，不得产出两条理由。"""
    from app.opportunity.decision import _UNKNOWN_REASON_CODES

    assert _UNKNOWN_REASON_CODES["conditional_reward"] == _UNKNOWN_REASON_CODES["conditional_reward_usd"]
    assert _UNKNOWN_REASON_CODES["hard_cost"] == _UNKNOWN_REASON_CODES["hard_cost_usd"]


def test_every_mapped_unknown_code_has_a_recommended_action():
    from app.opportunity.decision import _UNKNOWN_REASON_CODES

    assert set(_UNKNOWN_REASON_CODES.values()) <= set(WATCH_REASON_ACTIONS)


@pytest.mark.parametrize(
    "missing",
    [
        "event",
        "eligibility",
        "survival",
        "reward_probability",
        "economics",
        "conditional_reward_usd",
        "hard_cost_usd",
        "weekly_maintenance_hours",
        "project_quality",
        "project_failure_risk",
        "confidence",
        "risks",
        "participation_open",
        "task_path_known",
        "authorization_exit_known",
        "distribution_catalyst_3_6m",
        "project_active",
    ],
)
def test_unknown_values_never_crash_and_are_insufficient(passing_case, missing):
    case = passing_case
    if missing in {"event", "eligibility", "survival", "reward_probability", "economics"}:
        case = {**case, missing: None}
    elif missing in {"confidence", "risks"}:
        case = {
            **case,
            "inputs": case["inputs"].model_construct(**{**case["inputs"].__dict__, missing: None}),
        }
    else:
        case = _with_input(case, **{missing: None})
    result = decide(**case)
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"


@pytest.mark.parametrize("field", ["opportunity_timing", "profile_fit"])
def test_unknown_required_literal_is_insufficient(passing_case, field):
    result = decide(**_with_input(passing_case, **{field: "unknown"}))
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("event", "WAIT_CATALYST"),
        ("eligibility", "WAIT_EARLY_ENTRY"),
        ("survival", "WAIT_RULES"),
        ("reward_probability", "REWARD_TOO_UNCERTAIN"),
        ("conservative_net", "REWARD_TOO_UNCERTAIN"),
        ("base_net", "REWARD_TOO_UNCERTAIN"),
        ("reward_to_cost", "REWARD_TOO_UNCERTAIN"),
        ("hard_cost", "WAIT_COST_DROP"),
        ("weekly_maintenance", "WAIT_MORE_EVIDENCE"),
        ("quality", "WAIT_MORE_EVIDENCE"),
        ("project_failure", "WAIT_MORE_EVIDENCE"),
        ("overall_confidence", "WAIT_MORE_EVIDENCE"),
        ("event_confidence", "WAIT_MORE_EVIDENCE"),
        ("eligibility_confidence", "WAIT_MORE_EVIDENCE"),
        ("reward_confidence", "REWARD_TOO_UNCERTAIN"),
        ("cost_confidence", "WAIT_MORE_EVIDENCE"),
        ("risk_confidence", "WAIT_MORE_EVIDENCE"),
        ("airdrop_evidence_gate", "WAIT_MORE_EVIDENCE"),
    ],
)
def test_each_farm_threshold_prevents_actionable(passing_case, mutation, expected_code):
    case = passing_case
    if mutation == "event":
        case = {**case, "event": ProbabilityRange(low=0.49, base=0.70, high=0.80)}
    elif mutation == "eligibility":
        case = {**case, "eligibility": ProbabilityRange(low=0.49, base=0.70, high=0.85)}
    elif mutation == "survival":
        case = {**case, "survival": ProbabilityRange(low=0.59, base=0.80, high=0.90)}
    elif mutation == "reward_probability":
        case = {**case, "reward_probability": ProbabilityRange(low=0.19, base=0.39, high=0.61)}
    elif mutation == "conservative_net":
        case = {**case, "economics": _economics(net_reward=SignedMoneyRange(low=0, base=60, high=180))}
    elif mutation == "base_net":
        case = {**case, "economics": _economics(net_reward=SignedMoneyRange(low=20, base=29, high=180))}
    elif mutation == "reward_to_cost":
        case = {**case, "economics": _economics(reward_to_cost_ratio=2.99)}
    elif mutation == "hard_cost":
        case = _with_input(case, hard_cost_usd=MoneyRange(low=5, base=9, high=10.01))
    elif mutation == "weekly_maintenance":
        case = _with_input(case, weekly_maintenance_hours=2.01)
    elif mutation == "quality":
        case = _with_input(case, project_quality=49.99)
    elif mutation == "project_failure":
        case = _with_input(case, project_failure_risk=RiskLevel.HIGH)
    elif mutation.endswith("confidence"):
        field = mutation.removesuffix("_confidence")
        floors = {"overall": 0.649, "event": 0.699, "eligibility": 0.649, "reward": 0.499, "cost": 0.699, "risk": 0.699}
        case = _with_input(case, confidence=_confidence(**{field: floors[field]}))
    elif mutation == "airdrop_evidence_gate":
        case = _with_input(
            case,
            official_airdrop_evidence_count_a=0,
            independent_airdrop_evidence_count_b=1,
        )
    result = decide(**case)
    assert result.status == DecisionStatus.MONITOR
    assert result.public_label == "WATCH"
    assert result.watch_reason_codes[0] == expected_code


@pytest.mark.parametrize(
    ("a_count", "b_count"),
    [(1, 0), (2, 0), (0, 2), (0, 3), (1, 1)],
)
def test_airdrop_evidence_gate_accepts_a_or_two_independent_b(passing_case, a_count, b_count):
    result = decide(
        **_with_input(
            passing_case,
            official_airdrop_evidence_count_a=a_count,
            independent_airdrop_evidence_count_b=b_count,
        )
    )
    assert result.status == DecisionStatus.ACTIONABLE


@pytest.mark.parametrize(
    ("case_update", "code"),
    [
        ({"economics": _economics(net_reward=SignedMoneyRange(low=-20, base=-10, high=0))}, "NEGATIVE_EXPECTED_VALUE"),
        (
            {
                "economics": _economics(
                    gross_reward=MoneyRange(low=1, base=5, high=10), net_reward=SignedMoneyRange(low=1, base=5, high=10)
                )
            },
            "DUST_REWARD",
        ),
    ],
)
def test_explicit_structural_economics_are_not_fit(passing_case, case_update, code):
    result = decide(**{**passing_case, **case_update})
    assert result.status == DecisionStatus.NOT_FIT
    assert result.public_label == "IGNORE"
    assert result.ignore_reason_codes == (code,)
    assert result.expires_at == NOW + timedelta(days=30)


def test_permanently_excessive_cost_is_not_fit(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            hard_cost_usd=MoneyRange(low=10.01, base=12, high=15),
        )
    )
    assert result.status == DecisionStatus.NOT_FIT
    assert result.ignore_reason_codes == ("TOO_EXPENSIVE",)


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"weekly_maintenance_hours": 2.01, "weekly_time_confirmed_minimum": True}, "TOO_TIME_INTENSIVE"),
        ({"opportunity_timing": "late"}, "TOO_LATE"),
        ({"opportunity_timing": "closed"}, "TOO_LATE"),
        ({"project_active": False}, "PROJECT_INACTIVE"),
        ({"profile_fit": "mismatch"}, "PROFILE_MISMATCH"),
        ({"distribution_catalyst_3_6m": False}, "NO_AIRDROP_CASE"),
    ],
)
def test_explicit_structural_paths_are_not_fit(passing_case, updates, code):
    result = decide(**_with_input(passing_case, **updates))
    assert result.status == DecisionStatus.NOT_FIT
    assert result.public_label == "IGNORE"
    assert result.ignore_reason_codes == (code,)


def test_unconfirmed_excessive_weekly_time_remains_watch(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            weekly_maintenance_hours=2.01,
            weekly_time_confirmed_minimum=False,
        )
    )
    assert result.status == DecisionStatus.MONITOR
    assert result.public_label == "WATCH"


def test_single_wallet_profile_is_watch_unless_policy_forbids(passing_case):
    watch = decide(**_with_input(passing_case, profile_fit="single_wallet_only"))
    blocked = decide(
        **_with_input(
            passing_case,
            profile_fit="single_wallet_only",
            official_multiwallet_policy="forbidden",
        )
    )
    assert watch.status == DecisionStatus.MONITOR
    assert watch.watch_reason_codes == ("SINGLE_WALLET_ONLY",)
    assert blocked.status == DecisionStatus.BLOCKED
    assert blocked.blocker_codes == ("RULE_BLOCK",)


@pytest.mark.parametrize(
    ("updates", "status", "code"),
    [
        ({"participation_open": False}, DecisionStatus.MONITOR, "WAIT_TASK_OPEN"),
        ({"task_path_known": False}, DecisionStatus.INSUFFICIENT_EVIDENCE, "WAIT_RULES"),
        ({"authorization_exit_known": False}, DecisionStatus.INSUFFICIENT_EVIDENCE, "WAIT_MORE_EVIDENCE"),
    ],
)
def test_explicit_false_required_facts_fail_closed(passing_case, updates, status, code):
    result = decide(**_with_input(passing_case, **updates))
    assert result.status == status
    assert result.watch_reason_codes == (code,)


def test_unknown_policy_fails_closed_without_critical_unknown_string(passing_case):
    result = decide(
        **_with_input(
            passing_case,
            official_multiwallet_policy="unknown",
            critical_unknowns=(),
        )
    )
    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.watch_reason_codes == ("WAIT_RULES",)


@pytest.mark.parametrize(
    "risk_field",
    ["capital_security", "eligibility", "project_failure", "reward_dilution", "liquidity"],
)
def test_every_risk_dimension_is_required_for_farm(passing_case, risk_field):
    result = decide(
        **_with_input(
            passing_case,
            risks=_risks(**{risk_field: None}),
            **(
                {"capital_security_risk": None}
                if risk_field == "capital_security"
                else {"project_failure_risk": None}
                if risk_field == "project_failure"
                else {}
            ),
        )
    )

    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"


@pytest.mark.parametrize(
    ("risk_field", "reason"),
    [
        ("eligibility", "WAIT_RULES"),
        ("reward_dilution", "REWARD_TOO_UNCERTAIN"),
        ("liquidity", "REWARD_TOO_UNCERTAIN"),
    ],
)
@pytest.mark.parametrize("risk_level", list(RiskLevel))
def test_farm_gate_covers_every_level_of_reward_and_eligibility_risk(passing_case, risk_field, reason, risk_level):
    result = decide(**_with_input(passing_case, risks=_risks(**{risk_field: risk_level})))

    if risk_level in {RiskLevel.HIGH, RiskLevel.CRITICAL}:
        assert result.status == DecisionStatus.MONITOR
        assert result.public_label == "WATCH"
        assert reason in result.watch_reason_codes
    else:
        assert result.status == DecisionStatus.ACTIONABLE
        assert result.public_label == "FARM"


@pytest.mark.parametrize("field", ["safety_blocked", "integrity_blocked"])
def test_unknown_blocker_state_is_insufficient_without_unknown_string(passing_case, field):
    result = decide(**_with_input(passing_case, **{field: None}, critical_unknowns=()))

    assert result.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert result.public_label == "WATCH"


def test_inclusive_cost_time_and_probability_boundaries_are_actionable(passing_case):
    result = decide(
        **{
            **_with_input(
                passing_case,
                hard_cost_usd=MoneyRange(low=10, base=10, high=10),
                weekly_maintenance_hours=2,
                weekly_time_confirmed_minimum=True,
                project_quality=50,
                confidence=_confidence(
                    overall=0.65,
                    event=0.70,
                    eligibility=0.65,
                    reward=0.50,
                    cost=0.70,
                    risk=0.70,
                ),
            ),
            "event": ProbabilityRange(low=0.50, base=0.70, high=0.80),
            "eligibility": ProbabilityRange(low=0.50, base=0.70, high=0.85),
            "survival": ProbabilityRange(low=0.60, base=0.80, high=0.90),
            "reward_probability": ProbabilityRange(low=0.20, base=0.39, high=0.61),
            "economics": _economics(
                net_reward=SignedMoneyRange(low=0.01, base=30, high=180),
                reward_to_cost_ratio=3,
            ),
        }
    )
    assert result.status == DecisionStatus.ACTIONABLE


def test_optimistic_reward_cannot_rescue_negative_conservative_case(passing_case):
    result = decide(
        **{
            **passing_case,
            "economics": _economics(net_reward=SignedMoneyRange(low=-2, base=10, high=1000)),
        }
    )
    assert result.public_label != "FARM"


def test_monitor_uses_first_reason_action_and_seven_day_expiry(passing_case):
    result = decide(
        **{
            **passing_case,
            "event": ProbabilityRange(low=0.49, base=0.70, high=0.80),
            "eligibility": ProbabilityRange(low=0.49, base=0.70, high=0.85),
        }
    )
    assert result.watch_reason_codes[:2] == ("WAIT_CATALYST", "WAIT_EARLY_ENTRY")
    assert result.recommended_action == WATCH_REASON_ACTIONS["WAIT_CATALYST"]
    assert result.review_at == NOW + timedelta(days=7)
    assert result.expires_at == NOW + timedelta(days=7)


def test_insufficient_evidence_has_exact_action_and_expiry(passing_case):
    result = decide(**{**passing_case, "economics": None})
    assert result.recommended_action == "Collect the missing critical evidence before participating."
    assert result.review_at == NOW + timedelta(days=7)
    assert result.expires_at == NOW + timedelta(days=7)


def test_not_fit_and_blocked_have_exact_actions(passing_case):
    not_fit = decide(
        **{
            **passing_case,
            "economics": _economics(net_reward=SignedMoneyRange(low=-20, base=-10, high=0)),
        }
    )
    blocked = decide(**_with_input(passing_case, safety_blocked=True))
    assert not_fit.recommended_action == "Do not allocate time or funds under the current profile."
    assert blocked.recommended_action == ("Do not interact until credible remediation evidence is verified.")


def test_now_must_be_timezone_aware(passing_case):
    with pytest.raises(ValueError, match="timezone-aware"):
        decide(**{**passing_case, "now": datetime(2026, 7, 15, 12, 0)})


@pytest.mark.parametrize(
    ("mapping", "approved_codes"),
    [
        (
            WATCH_REASON_ACTIONS,
            {
                "WAIT_TASK_OPEN",
                "WAIT_RULES",
                "WAIT_CATALYST",
                "WAIT_COST_DROP",
                "WAIT_MORE_EVIDENCE",
                "WAIT_EARLY_ENTRY",
                "REWARD_TOO_UNCERTAIN",
                "SINGLE_WALLET_ONLY",
            },
        ),
        (
            IGNORE_REASON_ACTIONS,
            {
                "NEGATIVE_EXPECTED_VALUE",
                "DUST_REWARD",
                "TOO_EXPENSIVE",
                "TOO_TIME_INTENSIVE",
                "TOO_LATE",
                "NO_AIRDROP_CASE",
                "PROJECT_INACTIVE",
                "PROFILE_MISMATCH",
            },
        ),
        (BLOCK_REASON_ACTIONS, {"SAFETY_BLOCK", "INTEGRITY_BLOCK", "RULE_BLOCK"}),
    ],
)
def test_all_approved_reason_code_families_have_deterministic_actions(mapping, approved_codes):
    assert set(mapping) == approved_codes
    assert all(mapping[code] for code in approved_codes)
