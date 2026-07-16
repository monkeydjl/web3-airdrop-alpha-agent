from datetime import UTC, datetime, timedelta

import pytest

from app.opportunity.evidence import (
    CRITICAL_KEYS,
    FACTOR_SCHEMAS,
    SOURCE_GRADE_WEIGHT,
    SUPPORTED_FACTOR_KEYS,
    build_inputs,
    independent_count,
    resolve_factor,
    usable,
)
from app.opportunity.models import EvidenceRecord, RiskLevel
from app.opportunity.profile import DEFAULT_PROFILE

EXPECTED_FACTOR_KEYS = {
    "official_identity",
    "participation_open",
    "task_path_known",
    "authorization_exit_known",
    "official_airdrop_statement",
    "official_points_future_value",
    "community_allocation",
    "distribution_catalyst_3_6m",
    "project_active",
    "opportunity_timing",
    "profile_fit",
    "multiwallet_policy",
    "eligibility_mechanism",
    "hard_cost_usd",
    "weekly_maintenance_hours",
    "total_time_hours",
    "conditional_reward_usd",
    "capital_at_risk_usd",
    "expected_capital_loss_usd",
    "liquidity_cost_usd",
    "project_quality",
    "project_failure_risk",
    "capital_security_risk",
    "eligibility_risk",
    "reward_dilution_risk",
    "liquidity_risk",
    "integrity_blocked",
    "safety_blocked",
    "event_probability",
    "eligibility_probability",
    "survival_probability",
}


def _record(
    factor,
    value,
    grade="A",
    group="g1",
    *,
    evidence_id="generated-id",
    status="verified",
    observed_at="2026-07-14T00:00:00Z",
    effective_at=None,
    expires_at=None,
    value_type=None,
    project_id="p1",
    observation_type="observed",
):
    if value_type is None:
        if isinstance(value, bool):
            value_type = "bool"
        elif isinstance(value, (int, float)):
            value_type = "number"
        elif isinstance(value, dict):
            value_type = "range"
        else:
            value_type = "string"
    return EvidenceRecord(
        evidence_id=evidence_id,
        project_id=project_id,
        factor_key=factor,
        value=value,
        value_type=value_type,
        observation_type=observation_type,
        source_url="https://project.example/rules",
        source_type="official_docs",
        source_grade=grade,
        observed_at=observed_at,
        effective_at=effective_at,
        expires_at=expires_at,
        verification_status=status,
        independence_group=group,
    )


def test_source_grades_and_supported_factor_keys_are_closed():
    assert SOURCE_GRADE_WEIGHT == {"A": 1.0, "B": 0.8, "C": 0.5, "D": 0.2, "U": 0.0}
    assert SUPPORTED_FACTOR_KEYS == EXPECTED_FACTOR_KEYS
    assert set(FACTOR_SCHEMAS) == EXPECTED_FACTOR_KEYS


def test_explicit_decision_facts_are_populated_from_current_verified_evidence():
    records = [
        _record("participation_open", True, evidence_id="open"),
        _record("task_path_known", True, evidence_id="task"),
        _record("authorization_exit_known", True, evidence_id="exit"),
        _record("distribution_catalyst_3_6m", True, evidence_id="catalyst"),
        _record("project_active", True, evidence_id="active"),
        _record("opportunity_timing", "open", evidence_id="timing"),
        _record("profile_fit", "fit", evidence_id="fit"),
        _record("weekly_maintenance_hours", 3, evidence_id="weekly"),
    ]

    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert inputs.participation_open is True
    assert inputs.task_path_known is True
    assert inputs.authorization_exit_known is True
    assert inputs.distribution_catalyst_3_6m is True
    assert inputs.project_active is True
    assert inputs.opportunity_timing == "open"
    assert inputs.profile_fit == "fit"
    assert inputs.weekly_time_confirmed_minimum is True


@pytest.mark.parametrize(
    "factor,value",
    [
        ("task_path_known", True),
        ("authorization_exit_known", True),
        ("project_active", True),
        ("opportunity_timing", "open"),
        ("profile_fit", "fit"),
    ],
)
def test_new_decision_facts_require_id_current_verified_direct_provenance(factor, value):
    invalid_records = [
        _record(factor, value, evidence_id=None),
        _record(factor, value, evidence_id="unverified", status="unverified"),
        _record(factor, value, evidence_id="estimated", observation_type="estimated"),
        _record(factor, value, evidence_id="expired", expires_at="2020-01-01T00:00:00Z"),
    ]

    inputs = build_inputs({"id": "p1", "meta": "{}"}, invalid_records, DEFAULT_PROFILE)

    expected = "unknown" if factor in {"opportunity_timing", "profile_fit"} else None
    assert getattr(inputs, factor) == expected


def test_conflicting_explicit_decision_fact_remains_unknown():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record("project_active", True, evidence_id="active"),
            _record("project_active", False, evidence_id="inactive"),
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.project_active is None


@pytest.mark.parametrize("factor", ["safety_blocked", "integrity_blocked"])
def test_missing_or_unresolved_blocker_evidence_is_unknown(factor):
    missing = build_inputs({"id": "p1", "meta": "{}"}, [], DEFAULT_PROFILE)
    unresolved = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record(factor, False, evidence_id="conflicted", status="conflicted")],
        DEFAULT_PROFILE,
    )

    assert getattr(missing, factor) is None
    assert getattr(unresolved, factor) is None
    assert factor in missing.critical_unknowns
    assert factor in unresolved.critical_unknowns


@pytest.mark.parametrize("factor", ["safety_blocked", "integrity_blocked"])
def test_verified_false_blocker_evidence_clears_unknown(factor):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record(factor, False, evidence_id="verified-false")],
        DEFAULT_PROFILE,
    )

    assert getattr(inputs, factor) is False
    assert factor not in inputs.critical_unknowns


def test_official_identity_is_explicit_tri_state_and_false_safety_blocks():
    missing = build_inputs({"id": "p1", "meta": "{}"}, [], DEFAULT_PROFILE)
    verified = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("official_identity", True, evidence_id="identity-true")],
        DEFAULT_PROFILE,
    )
    rejected = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("official_identity", False, evidence_id="identity-false")],
        DEFAULT_PROFILE,
    )

    assert "official_identity" in missing.critical_unknowns
    assert "official_identity" not in verified.critical_unknowns
    assert rejected.safety_blocked is True
    assert "official_identity" not in rejected.critical_unknowns


@pytest.mark.parametrize("factor", ["safety_blocked", "integrity_blocked"])
def test_any_current_verified_true_blocker_wins_over_false_conflict(factor):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(factor, False, grade="A", evidence_id="false"),
            _record(factor, True, grade="B", evidence_id="true"),
        ],
        DEFAULT_PROFILE,
    )

    assert getattr(inputs, factor) is True
    assert factor not in inputs.critical_unknowns


@pytest.mark.parametrize("factor", ["safety_blocked", "integrity_blocked"])
@pytest.mark.parametrize("observation_type", ["estimated", "assumed"])
@pytest.mark.parametrize("value", [True, False])
def test_indirect_blocker_evidence_cannot_block_or_clear(factor, observation_type, value):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                factor,
                value,
                evidence_id="indirect-blocker",
                observation_type=observation_type,
            )
        ],
        DEFAULT_PROFILE,
    )

    assert getattr(inputs, factor) is None
    assert factor in inputs.critical_unknowns


@pytest.mark.parametrize(
    ("observation_type", "grade", "confirmed"),
    [
        ("observed", "A", True),
        ("derived", "B", True),
        ("estimated", "A", False),
        ("assumed", "A", False),
        ("observed", "C", False),
    ],
)
def test_weekly_time_confirmation_requires_direct_current_grade_b_evidence(observation_type, grade, confirmed):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                "weekly_maintenance_hours",
                3,
                grade=grade,
                evidence_id="weekly",
                observation_type=observation_type,
            )
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.weekly_maintenance_hours == 3
    assert inputs.weekly_time_confirmed_minimum is confirmed


@pytest.mark.parametrize(
    "record",
    [
        _record("weekly_maintenance_hours", 3, evidence_id=None),
        _record(
            "weekly_maintenance_hours",
            3,
            evidence_id="expired",
            expires_at="2020-01-01T00:00:00Z",
        ),
        _record(
            "weekly_maintenance_hours",
            3,
            evidence_id="unverified",
            status="unverified",
        ),
    ],
)
def test_non_current_weekly_time_cannot_be_confirmed(record):
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE)

    assert inputs.weekly_time_confirmed_minimum is False


def test_reposts_count_as_one_independent_source():
    records = [
        _record("official_airdrop_statement", True, "B", "same-announcement"),
        _record("official_airdrop_statement", True, "B", "same-announcement"),
        _record("community_allocation", True, "C", "different-low-grade"),
        _record(
            "official_points_future_value",
            True,
            "A",
            "unverified",
            status="unverified",
        ),
    ]
    assert independent_count(records, minimum_grade="B") == 1


@pytest.mark.parametrize(
    "factor",
    ["official_airdrop_statement", "community_allocation"],
)
def test_false_a_grade_airdrop_basis_does_not_count_or_clear_unknown(factor):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record(factor, False, grade="A", evidence_id=f"false-{factor}")],
        DEFAULT_PROFILE,
    )

    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.independent_airdrop_evidence_count_b == 0
    assert "airdrop_basis" in inputs.critical_unknowns


def test_only_affirmative_independent_airdrop_records_count_as_support():
    records = [
        _record(
            "official_airdrop_statement",
            False,
            grade="A",
            group="negative-statement",
            evidence_id="negative",
        ),
        _record(
            "community_allocation",
            True,
            grade="B",
            group="affirmative-allocation",
            evidence_id="affirmative",
        ),
        _record(
            "official_points_future_value",
            False,
            grade="A",
            group="negative-points",
            evidence_id="negative-points",
        ),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.independent_airdrop_evidence_count_b == 1
    assert "airdrop_basis" not in inputs.critical_unknowns
    assert inputs.evidence_ids == ("affirmative", "negative", "negative-points")


def test_newer_false_restores_unknown_unless_an_independent_affirmative_remains():
    superseded = [
        _record(
            "official_airdrop_statement",
            True,
            group="official-statement",
            evidence_id="older-true",
            observed_at="2026-07-12T00:00:00Z",
        ),
        _record(
            "official_airdrop_statement",
            False,
            group="official-statement",
            evidence_id="newer-false",
            observed_at="2026-07-13T00:00:00Z",
        ),
    ]
    restored = build_inputs({"id": "p1", "meta": "{}"}, superseded, DEFAULT_PROFILE)
    supported = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            *superseded,
            _record(
                "community_allocation",
                True,
                grade="B",
                group="independent-allocation",
                evidence_id="independent-true",
                observed_at="2026-07-11T00:00:00Z",
            ),
        ],
        DEFAULT_PROFILE,
    )

    assert restored.official_airdrop_evidence_count_a == 0
    assert restored.independent_airdrop_evidence_count_b == 0
    assert "airdrop_basis" in restored.critical_unknowns
    assert supported.official_airdrop_evidence_count_a == 0
    assert supported.independent_airdrop_evidence_count_b == 1
    assert "airdrop_basis" not in supported.critical_unknowns


def test_idless_evidence_cannot_set_clear_count_or_enter_audit():
    records = [
        _record("official_identity", True, evidence_id=None),
        _record("participation_open", True, evidence_id=""),
        _record("official_airdrop_statement", True, evidence_id="   "),
        _record("multiwallet_policy", "allowed", evidence_id=None),
        _record("hard_cost_usd", {"low": 0, "base": 0, "high": 0}, evidence_id=None),
        _record("weekly_maintenance_hours", 0, evidence_id=None),
        _record("capital_security_risk", "low", evidence_id=None),
        _record(
            "conditional_reward_usd",
            {"low": 10, "base": 20, "high": 30},
            evidence_id=None,
        ),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert set(inputs.critical_unknowns) == CRITICAL_KEYS
    assert inputs.official_multiwallet_policy == "unknown"
    assert inputs.hard_cost_usd is None
    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.independent_airdrop_evidence_count_b == 0
    assert inputs.evidence_ids == ()


def test_usable_rejects_expired_conflicted_and_invalidated_evidence():
    now = datetime(2026, 7, 14, tzinfo=UTC)
    assert usable(_record("official_identity", True), now)
    assert not usable(_record("official_identity", True, expires_at="2026-07-14T00:00:00Z"), now)
    assert not usable(_record("official_identity", True, status="conflicted"), now)
    assert not usable(_record("official_identity", True, status="invalidated"), now)
    assert not usable(_record("official_identity", True, status="unverified"), now)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"observed_at": "2026-07-14T00:00:00Z"}, True),
        ({"observed_at": "2026-07-14T00:00:01Z"}, False),
        ({"effective_at": "2026-07-14T00:00:00Z"}, True),
        ({"effective_at": "2026-07-14T00:00:01Z"}, False),
        ({"expires_at": "2026-07-14T00:00:00Z"}, False),
        ({"expires_at": "2026-07-14T00:00:01Z"}, True),
    ],
)
def test_usable_enforces_temporal_boundaries(overrides, expected):
    now = datetime(2026, 7, 14, tzinfo=UTC)
    assert usable(_record("official_identity", True, **overrides), now) is expected


def test_usable_normalizes_naive_datetimes_as_utc_consistently():
    now = datetime(2026, 7, 14)
    assert usable(
        _record(
            "official_identity",
            True,
            observed_at=datetime(2026, 7, 14),
            effective_at=datetime(2026, 7, 14),
            expires_at=datetime(2026, 7, 14, 0, 0, 1),
        ),
        now,
    )


@pytest.mark.parametrize("temporal_field", ["observed_at", "effective_at"])
def test_future_evidence_cannot_affect_inputs_or_audit_ids(temporal_field):
    now = datetime(2026, 7, 14, tzinfo=UTC)
    future = now + timedelta(seconds=1)
    records = [
        _record("safety_blocked", True, evidence_id="future-blocker", **{temporal_field: future}),
        _record("official_airdrop_statement", True, evidence_id="future-count", **{temporal_field: future}),
        _record(
            "event_probability",
            {"low": 0.8, "base": 0.9, "high": 1.0},
            evidence_id="future-probability",
            **{temporal_field: future},
        ),
        _record(
            "conditional_reward_usd",
            {"low": 10, "base": 20, "high": 30},
            evidence_id="future-economics",
            **{temporal_field: future},
        ),
        _record("project_quality", 90, evidence_id="future-confidence", **{temporal_field: future}),
    ]

    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE, now=now)

    assert inputs.safety_blocked is None
    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.event_probability is None
    assert inputs.conditional_reward_usd is None
    assert inputs.project_quality is None
    assert set(inputs.critical_unknowns) == CRITICAL_KEYS
    assert inputs.evidence_ids == ()


@pytest.mark.parametrize("temporal_field", ["observed_at", "effective_at"])
def test_future_supersession_cannot_clear_current_blocker(temporal_field):
    now = datetime(2026, 7, 14, tzinfo=UTC)
    active = _record(
        "safety_blocked",
        True,
        evidence_id="active-blocker",
        observed_at=now - timedelta(seconds=1),
    )
    timestamps = {"observed_at": now, temporal_field: now + timedelta(seconds=1)}
    future_clear = _record(
        "safety_blocked",
        False,
        evidence_id="future-clear",
        **timestamps,
    ).model_copy(update={"supersedes_evidence_id": active.evidence_id})

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [active, future_clear], DEFAULT_PROFILE, now=now)

    assert inputs.safety_blocked is True
    assert inputs.evidence_ids == ("active-blocker",)


def test_legacy_signals_never_create_complete_or_quantified_inputs():
    row = {
        "id": "p1",
        "stage": "testnet",
        "meta": (
            '{"signals":{"no_token_yet":true,"has_points_program":true,'
            '"airdrop_confirmed":true,"multiwallet_allowed":true,'
            '"free_to_participate":true}}'
        ),
    }
    inputs = build_inputs(row, [], DEFAULT_PROFILE)
    assert set(inputs.critical_unknowns) == CRITICAL_KEYS
    assert inputs.event_probability is None
    assert inputs.eligibility_probability is None
    assert inputs.survival_probability is None
    assert inputs.conditional_reward_usd is None
    assert inputs.hard_cost_usd is None
    assert inputs.official_multiwallet_policy == "unknown"
    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.independent_airdrop_evidence_count_b == 0
    assert inputs.evidence_ids == ()


def test_malformed_or_non_object_legacy_meta_is_ignored():
    for meta in ("not-json", "[]", None, {"signals": [True]}):
        inputs = build_inputs({"id": "p1", "meta": meta}, [], DEFAULT_PROFILE)
        assert set(inputs.critical_unknowns) == CRITICAL_KEYS


def test_same_grade_contradictory_active_evidence_is_unresolved_despite_timestamp():
    records = [
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="old",
            observed_at="2026-07-10T00:00:00Z",
        ),
        _record(
            "multiwallet_policy",
            "not_forbidden",
            evidence_id="new-partial",
            status="partially_verified",
            observed_at="2026-07-13T00:00:00Z",
        ),
        _record(
            "multiwallet_policy",
            "forbidden",
            evidence_id="new-verified",
            observed_at="2026-07-12T00:00:00Z",
        ),
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="expired",
            observed_at="2026-07-14T00:00:00Z",
            expires_at="2020-01-01T00:00:00Z",
        ),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)
    assert inputs.official_multiwallet_policy == "unknown"
    assert "multiwallet_policy" in inputs.critical_unknowns
    assert inputs.evidence_ids == ("new-partial", "new-verified", "old")


def test_verified_forbidden_policy_is_preserved():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("multiwallet_policy", "forbidden", evidence_id="policy")],
        DEFAULT_PROFILE,
    )
    assert inputs.official_multiwallet_policy == "forbidden"


def test_explicit_ranges_and_scalar_factors_are_normalized():
    complete = [
        _record("official_identity", True, evidence_id="identity"),
        _record("participation_open", True, evidence_id="open"),
        _record("task_path_known", True, evidence_id="task-path"),
        _record("authorization_exit_known", True, evidence_id="authorization-exit"),
        _record("distribution_catalyst_3_6m", True, evidence_id="catalyst"),
        _record("project_active", True, evidence_id="active"),
        _record("opportunity_timing", "open", evidence_id="timing"),
        _record("profile_fit", "fit", evidence_id="profile-fit"),
        _record("official_airdrop_statement", True, group="airdrop-a", evidence_id="airdrop-a"),
        _record("community_allocation", True, grade="B", group="airdrop-b", evidence_id="airdrop-b"),
        _record("multiwallet_policy", "allowed", evidence_id="policy"),
        _record("hard_cost_usd", {"low": 1, "base": 2, "high": 3}, evidence_id="hard-cost"),
        _record("weekly_maintenance_hours", 1.5, evidence_id="weekly"),
        _record("total_time_hours", {"low": 2, "base": 3, "high": 4}, evidence_id="time"),
        _record("conditional_reward_usd", {"low": 20, "base": 50, "high": 100}, evidence_id="reward"),
        _record("capital_at_risk_usd", {"low": 5, "base": 10, "high": 20}, evidence_id="capital"),
        _record("expected_capital_loss_usd", {"low": 0, "base": 1, "high": 2}, evidence_id="loss"),
        _record("liquidity_cost_usd", {"low": 0, "base": 0, "high": 1}, evidence_id="liquidity"),
        _record("event_probability", {"low": 0.4, "base": 0.6, "high": 0.8}, evidence_id="event"),
        _record("eligibility_probability", {"low": 0.5, "base": 0.7, "high": 0.9}, evidence_id="eligibility"),
        _record("survival_probability", {"low": 0.6, "base": 0.8, "high": 1}, evidence_id="survival"),
        _record("project_quality", 72, evidence_id="quality"),
        _record("project_failure_risk", "medium", evidence_id="failure-risk"),
        _record("capital_security_risk", "critical", evidence_id="security-risk"),
        _record("eligibility_risk", "low", evidence_id="eligibility-risk"),
        _record("reward_dilution_risk", "medium", evidence_id="dilution-risk"),
        _record("liquidity_risk", "low", evidence_id="liquidity-risk"),
        _record("integrity_blocked", False, evidence_id="integrity"),
        _record("safety_blocked", False, evidence_id="safety"),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, complete, DEFAULT_PROFILE)
    assert inputs.critical_unknowns == ()
    assert inputs.event_probability.model_dump() == {"low": 0.4, "base": 0.6, "high": 0.8}
    assert inputs.hard_cost_usd.model_dump() == {"low": 1.0, "base": 2.0, "high": 3.0}
    assert inputs.capital_at_risk_usd.model_dump() == {"low": 5.0, "base": 10.0, "high": 20.0}
    assert inputs.weekly_maintenance_hours == 1.5
    assert inputs.project_quality == 72
    assert inputs.project_failure_risk == RiskLevel.MEDIUM
    assert inputs.capital_security_risk == RiskLevel.CRITICAL
    assert inputs.risks.capital_security == RiskLevel.CRITICAL
    assert inputs.risks.eligibility == RiskLevel.LOW
    assert inputs.risks.reward_dilution == RiskLevel.MEDIUM
    assert inputs.risks.liquidity == RiskLevel.LOW
    assert inputs.official_airdrop_evidence_count_a == 1
    assert inputs.independent_airdrop_evidence_count_b == 2
    assert inputs.evidence_ids == tuple(sorted(record.evidence_id for record in complete))


@pytest.mark.parametrize(
    ("factor", "value", "value_type"),
    [
        ("official_identity", 1, "bool"),
        ("official_identity", "true", "bool"),
        ("official_identity", None, "bool"),
        ("official_identity", True, "number"),
        ("multiwallet_policy", "yes", "string"),
        ("multiwallet_policy", "allowed", "json"),
        ("eligibility_mechanism", "random", "string"),
        ("project_failure_risk", "unknown", "string"),
        ("weekly_maintenance_hours", True, "number"),
        ("weekly_maintenance_hours", -0.1, "number"),
        ("project_quality", 101, "number"),
        ("event_probability", {"low": 0.2, "base": 0.4}, "range"),
        ("event_probability", {"low": 0.2, "base": 0.4, "high": 0.6, "extra": 1}, "range"),
        ("event_probability", {"low": 0.2, "base": 0.4, "high": 1.1}, "range"),
        ("event_probability", {"low": 0.6, "base": 0.4, "high": 0.8}, "range"),
        ("hard_cost_usd", {"low": -1, "base": 0, "high": 1}, "range"),
        ("total_time_hours", [1, 2, 3], "range"),
    ],
)
def test_malformed_factor_evidence_is_ignored(factor, value, value_type):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record(factor, value, evidence_id="malformed", value_type=value_type)],
        DEFAULT_PROFILE,
    )
    assert inputs.evidence_ids == ()
    assert set(inputs.critical_unknowns) == CRITICAL_KEYS


@pytest.mark.parametrize(
    ("factor", "invalid_member"),
    [
        ("event_probability", "0.4"),
        ("event_probability", True),
        ("hard_cost_usd", "2"),
        ("hard_cost_usd", False),
        ("total_time_hours", "2"),
        ("total_time_hours", True),
    ],
)
def test_range_members_require_exact_finite_numbers(factor, invalid_member):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                factor,
                {"low": 0, "base": invalid_member, "high": 3},
                evidence_id="invalid-range",
                value_type="range",
            )
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.evidence_ids == ()


def test_oversized_integer_range_member_is_ignored_and_preserves_unknown():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                "hard_cost_usd",
                {"low": 0, "base": 10**10000, "high": 10**10001},
                evidence_id="oversized-range",
                value_type="range",
            )
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.hard_cost_usd is None
    assert "hard_cost" in inputs.critical_unknowns
    assert inputs.evidence_ids == ()


def test_oversized_integer_scalar_is_ignored_and_preserves_unknown():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                "weekly_maintenance_hours",
                10**10000,
                evidence_id="oversized-scalar",
                value_type="number",
            )
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.weekly_maintenance_hours is None
    assert "weekly_maintenance" in inputs.critical_unknowns
    assert inputs.evidence_ids == ()


@pytest.mark.parametrize(
    "mechanism",
    ["deterministic", "points_based", "behavioral", "opaque"],
)
def test_documented_eligibility_mechanisms_are_retained(mechanism):
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [
            _record(
                "eligibility_mechanism",
                mechanism,
                evidence_id=f"mechanism-{mechanism}",
            )
        ],
        DEFAULT_PROFILE,
    )

    assert inputs.evidence_ids == (f"mechanism-{mechanism}",)


def test_undocumented_points_eligibility_mechanism_is_rejected():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("eligibility_mechanism", "points", evidence_id="undocumented")],
        DEFAULT_PROFILE,
    )

    assert inputs.evidence_ids == ()


def test_unknown_factor_is_not_consumed_or_retained_for_audit():
    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [_record("magic_score", 100, evidence_id="unsupported")],
        DEFAULT_PROFILE,
    )
    assert inputs.evidence_ids == ()
    assert set(inputs.critical_unknowns) == CRITICAL_KEYS


def test_only_present_evidence_ids_are_sorted_and_deduplicated():
    records = [
        _record("official_identity", True, evidence_id="z"),
        _record("participation_open", True, evidence_id="a"),
        _record("community_allocation", True, evidence_id="z", group="other"),
        _record("hard_cost_usd", {"low": 0, "base": 0, "high": 0}, evidence_id=None),
        _record("safety_blocked", False, evidence_id="bad", status="conflicted"),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)
    assert inputs.evidence_ids == ("a", "z")


def test_build_inputs_ignores_other_and_missing_project_evidence_everywhere():
    own = _record(
        "community_allocation",
        True,
        grade="B",
        group="own-basis",
        evidence_id="own-b",
    )
    records = [
        own,
        _record(
            "official_airdrop_statement",
            True,
            grade="A",
            group="foreign-a",
            evidence_id="foreign-a",
            project_id="p2",
        ),
        _record(
            "official_points_future_value",
            True,
            grade="A",
            group="missing-a",
            evidence_id="missing-a",
            project_id=None,
        ),
        _record(
            "event_probability",
            {"low": 0.7, "base": 0.8, "high": 0.9},
            evidence_id="foreign-range",
            project_id="p2",
        ),
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="missing-policy",
            project_id=None,
        ),
    ]

    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert inputs.event_probability is None
    assert inputs.official_multiwallet_policy == "unknown"
    assert inputs.official_airdrop_evidence_count_a == 0
    assert inputs.independent_airdrop_evidence_count_b == 1
    assert inputs.evidence_ids == ("own-b",)


def test_sparse_inputs_keep_unknown_risks_explicit():
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [], DEFAULT_PROFILE)
    assert set(inputs.confidence.model_dump().values()) == {0.0}
    assert set(inputs.risks.model_dump().values()) == {None}


def test_equal_instant_conflicting_values_are_unusable_across_offsets():
    records = [
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="a",
            observed_at="2026-07-14T00:00:00Z",
        ),
        _record(
            "multiwallet_policy",
            "forbidden",
            evidence_id="b",
            observed_at="2026-07-14T08:00:00+08:00",
        ),
    ]
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)

    assert inputs.official_multiwallet_policy == "unknown"
    assert "multiwallet_policy" in inputs.critical_unknowns
    assert inputs.evidence_ids == ("a", "b")


def test_equal_instant_identical_values_choose_smallest_id_deterministically():
    records = [
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="z",
            observed_at="2026-07-14T08:00:00+08:00",
        ),
        _record(
            "multiwallet_policy",
            "allowed",
            evidence_id="a",
            observed_at="2026-07-14T00:00:00Z",
        ),
    ]
    forward = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE)
    reverse = build_inputs({"id": "p1", "meta": "{}"}, list(reversed(records)), DEFAULT_PROFILE)

    assert forward.official_multiwallet_policy == "allowed"
    assert reverse == forward
    assert forward.evidence_ids == ("a", "z")


def test_resolve_factor_returns_current_normalized_record_and_value():
    record = _record(
        "hard_cost_usd",
        {"low": 1, "base": 2, "high": 3},
        evidence_id="cost",
    )

    resolution = resolve_factor([record], "hard_cost_usd")

    assert resolution.conflicted is False
    assert resolution.record is record
    assert resolution.value.model_dump() == {"low": 1.0, "base": 2.0, "high": 3.0}


def test_resolve_factor_reports_same_grade_contradiction_regardless_timestamp():
    resolution = resolve_factor(
        [
            _record(
                "multiwallet_policy",
                "allowed",
                evidence_id="old",
                observed_at="2026-07-10T00:00:00Z",
            ),
            _record(
                "multiwallet_policy",
                "forbidden",
                evidence_id="new",
                observed_at="2026-07-14T00:00:00Z",
            ),
        ],
        "multiwallet_policy",
    )

    assert resolution.conflicted is True
    assert resolution.record is None
    assert resolution.value is None


def test_resolve_factor_accepts_newer_higher_grade_superseding_lower_grade():
    newer = _record(
        "multiwallet_policy",
        "allowed",
        grade="A",
        evidence_id="new-a",
        observed_at="2026-07-14T00:00:00Z",
    )
    resolution = resolve_factor(
        [
            _record(
                "multiwallet_policy",
                "forbidden",
                grade="B",
                evidence_id="old-b",
                observed_at="2026-07-10T00:00:00Z",
            ),
            newer,
        ],
        "multiwallet_policy",
    )

    assert resolution.conflicted is False
    assert resolution.record is newer
    assert resolution.value == "allowed"


def test_resolve_factor_rejects_older_higher_grade_against_newer_lower_grade():
    resolution = resolve_factor(
        [
            _record(
                "multiwallet_policy",
                "allowed",
                grade="A",
                evidence_id="old-a",
                observed_at="2026-07-10T00:00:00Z",
            ),
            _record(
                "multiwallet_policy",
                "forbidden",
                grade="B",
                evidence_id="new-b",
                observed_at="2026-07-14T00:00:00Z",
            ),
        ],
        "multiwallet_policy",
    )

    assert resolution.conflicted is True
    assert resolution.record is None


@pytest.mark.parametrize("status", ["partially_verified", "unverified", "conflicted", "invalidated"])
def test_resolve_factor_excludes_non_verified_statuses(status):
    resolution = resolve_factor(
        [_record("participation_open", True, status=status)],
        "participation_open",
    )
    assert resolution.record is None
    assert resolution.conflicted is False


def test_resolve_factor_excludes_expired_and_malformed_records():
    resolution = resolve_factor(
        [
            _record(
                "participation_open",
                True,
                evidence_id="expired",
                expires_at="2020-01-01T00:00:00Z",
            ),
            _record(
                "participation_open",
                "true",
                evidence_id="malformed",
                value_type="bool",
            ),
        ],
        "participation_open",
    )
    assert resolution.record is None
    assert resolution.value is None


def test_naive_evidence_timestamps_are_treated_as_utc_deterministically():
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    record = _record(
        "participation_open",
        True,
        evidence_id="naive-time",
        observed_at=datetime(2026, 7, 15, 11),
        expires_at=datetime(2026, 7, 15, 13),
    )

    assert usable(record, now)
    assert resolve_factor([record], "participation_open", now).record is record


def test_a_grade_false_remediation_supersedes_true_blocker_append_only():
    original = _record("safety_blocked", True, evidence_id="blocker")
    remediation = _record(
        "safety_blocked",
        False,
        evidence_id="remediation",
        observed_at="2026-07-15T00:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "blocker"})

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [original, remediation], DEFAULT_PROFILE)

    assert inputs.safety_blocked is False


def test_true_confirmation_then_strong_false_clears_entire_active_lineage():
    original = _record("safety_blocked", True, evidence_id="original")
    confirmation = _record(
        "safety_blocked",
        True,
        evidence_id="confirmation",
        observed_at="2026-07-14T01:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "original"})
    remediation = _record(
        "safety_blocked",
        False,
        evidence_id="remediation",
        observed_at="2026-07-14T02:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "confirmation"})

    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [original, confirmation, remediation],
        DEFAULT_PROFILE,
    )

    assert inputs.safety_blocked is False
    assert "remediation" in inputs.evidence_ids


def test_weak_false_chain_tip_leaves_latest_true_confirmation_active():
    original = _record("safety_blocked", True, evidence_id="original")
    confirmation = _record(
        "safety_blocked",
        True,
        evidence_id="confirmation",
        observed_at="2026-07-14T01:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "original"})
    weak = _record(
        "safety_blocked",
        False,
        grade="B",
        evidence_id="weak",
        observed_at="2026-07-14T02:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "confirmation"})

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [original, confirmation, weak], DEFAULT_PROFILE)

    assert inputs.safety_blocked is True
    assert "confirmation" in inputs.evidence_ids


def test_branching_lineage_stays_blocked_while_any_active_tip_is_true():
    original = _record("safety_blocked", True, evidence_id="original")
    cleared_branch = _record(
        "safety_blocked",
        False,
        evidence_id="cleared",
        observed_at="2026-07-14T01:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "original"})
    confirmed_branch = _record(
        "safety_blocked",
        True,
        evidence_id="confirmed",
        observed_at="2026-07-14T02:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "original"})

    inputs = build_inputs(
        {"id": "p1", "meta": "{}"},
        [original, cleared_branch, confirmed_branch],
        DEFAULT_PROFILE,
    )

    assert inputs.safety_blocked is True
    assert "confirmed" in inputs.evidence_ids


def test_backdated_supersession_edge_is_ignored_conservatively():
    blocker = _record(
        "safety_blocked",
        True,
        evidence_id="blocker",
        observed_at="2026-07-14T02:00:00Z",
    )
    backdated = _record(
        "safety_blocked",
        False,
        evidence_id="backdated",
        observed_at="2026-07-14T01:00:00Z",
    ).model_copy(update={"supersedes_evidence_id": "blocker"})

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [blocker, backdated], DEFAULT_PROFILE)

    assert inputs.safety_blocked is True


@pytest.mark.parametrize(
    "updates",
    [
        {"source_grade": "B"},
        {"verification_status": "partially_verified"},
        {"observation_type": "estimated"},
        {"value": True},
    ],
)
def test_weak_or_non_false_remediation_cannot_clear_blocker(updates):
    original = _record("safety_blocked", True, evidence_id="blocker")
    remediation = _record("safety_blocked", False, evidence_id="weak-remediation").model_copy(
        update={"supersedes_evidence_id": "blocker", **updates}
    )

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [original, remediation], DEFAULT_PROFILE)

    assert inputs.safety_blocked is True


def test_circular_supersession_is_conservative():
    first = _record("safety_blocked", False, evidence_id="first").model_copy(
        update={"supersedes_evidence_id": "second"}
    )
    second = _record("safety_blocked", False, evidence_id="second").model_copy(
        update={"supersedes_evidence_id": "first"}
    )

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [first, second], DEFAULT_PROFILE)

    assert inputs.safety_blocked is None
    assert set(inputs.evidence_ids) == {"first", "second"}


def test_cycle_containing_true_blocker_remains_blocked_conservatively():
    first = _record("safety_blocked", True, evidence_id="first").model_copy(update={"supersedes_evidence_id": "second"})
    second = _record("safety_blocked", False, evidence_id="second").model_copy(
        update={"supersedes_evidence_id": "first"}
    )

    inputs = build_inputs({"id": "p1", "meta": "{}"}, [first, second], DEFAULT_PROFILE)

    assert inputs.safety_blocked is True


def test_expiry_equal_to_now_is_unusable_everywhere():
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    record = _record(
        "participation_open",
        True,
        evidence_id="expires-now",
        observed_at=now - timedelta(days=1),
        expires_at=now,
    )

    resolution = resolve_factor([record], "participation_open", now)
    inputs = build_inputs({"id": "p1", "meta": "{}"}, [record], DEFAULT_PROFILE, now=now)

    assert resolution.record is None
    assert inputs.participation_open is None
    assert inputs.evidence_ids == ()


def test_factor_specific_future_expiry_keeps_old_evidence_usable():
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    record = _record(
        "participation_open",
        True,
        evidence_id="old-but-authoritative",
        observed_at=now - timedelta(days=365),
        expires_at=now + timedelta(seconds=1),
    )

    resolution = resolve_factor([record], "participation_open", now)

    assert resolution.record is record
    assert resolution.consistency == 1.0


def test_resolution_reports_superseded_and_unresolved_consistency():
    now = datetime(2026, 7, 15, 12, tzinfo=UTC)
    selected = _record(
        "multiwallet_policy",
        "allowed",
        grade="A",
        evidence_id="selected",
        observed_at=now - timedelta(days=1),
    )
    lower = _record(
        "multiwallet_policy",
        "forbidden",
        grade="B",
        evidence_id="lower",
        observed_at=now - timedelta(days=2),
    )
    same_grade = lower.model_copy(update={"evidence_id": "same-grade", "source_grade": "A"})

    superseded = resolve_factor([lower, selected], "multiwallet_policy", now)
    unresolved = resolve_factor([same_grade, selected], "multiwallet_policy", now)

    assert superseded.record is selected
    assert superseded.consistency == 0.5
    assert unresolved.record is None
    assert unresolved.consistency == 0.0
