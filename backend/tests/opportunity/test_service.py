import sqlite3
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.db import init_db
from app.opportunity.evidence import build_inputs
from app.opportunity.models import DecisionStatus, EvidenceRecord
from app.opportunity.profile import DEFAULT_PROFILE
from app.opportunity.repository import OpportunityRepository
from app.opportunity.service import OpportunityService, _build_confidence
from app.repository import ProjectRepository

NOW = datetime(2026, 7, 15, 12, tzinfo=UTC)
SNAPSHOT_KEYS = {
    "event_probability",
    "eligibility_probability",
    "survival_probability",
    "conditional_reward_usd",
    "hard_cost_usd",
    "capital_at_risk_usd",
    "expected_capital_loss_usd",
    "liquidity_cost_usd",
    "total_time_hours",
    "weekly_maintenance_hours",
    "project_quality",
    "risks",
    "confidence",
    "critical_unknowns",
    "official_airdrop_evidence_count_a",
    "independent_airdrop_evidence_count_b",
}


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)
    connection.execute(
        """INSERT INTO projects
               (id, name, sector, stage, score, label, confidence, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("p1", "Legacy Alpha", "DeFi", "testnet", 90, "FARM", 0.95, "seed"),
    )
    connection.commit()
    yield connection
    connection.close()


def _evidence(factor_key, value, *, evidence_id=None, **overrides):
    value_types = {
        bool: "bool",
        float: "number",
        int: "number",
        str: "string",
        dict: "range",
    }
    data = {
        "evidence_id": evidence_id or f"e-{factor_key}",
        "project_id": "p1",
        "factor_key": factor_key,
        "value": value,
        "value_type": value_types[type(value)],
        "observation_type": "observed",
        "source_url": f"https://evidence.example/{factor_key}",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": NOW - timedelta(hours=1),
        "expires_at": NOW + timedelta(days=30),
        "verification_status": "verified",
        "independence_group": f"source-{factor_key}",
        "raw_snapshot_ref": f"raw/{factor_key}",
    }
    data.update(overrides)
    return EvidenceRecord(**data)


def _complete_evidence():
    official = {"independence_group": "official-rules"}
    probability = {
        "observation_type": "derived",
        "source_grade": "B",
        "source_type": "scoring_model",
        "independence_group": "probability-model",
    }
    economics = {
        "observation_type": "derived",
        "source_grade": "B",
        "source_type": "cost_model",
        "independence_group": "economics-model",
    }
    risk = {
        "observation_type": "derived",
        "source_grade": "A",
        "source_type": "verified_risk_model",
        "independence_group": "risk-review",
    }
    return [
        _evidence("official_identity", True, **official),
        _evidence("participation_open", True, **official),
        _evidence("task_path_known", True, **official),
        _evidence("authorization_exit_known", True, **official),
        _evidence("official_airdrop_statement", True, **official),
        _evidence("distribution_catalyst_3_6m", True, **official),
        _evidence("project_active", True, **official),
        _evidence("opportunity_timing", "open", **official),
        _evidence("profile_fit", "fit", **official),
        _evidence("multiwallet_policy", "allowed", **official),
        _evidence("eligibility_mechanism", "deterministic", **official),
        _evidence("integrity_blocked", False, **official),
        _evidence("safety_blocked", False, **official),
        _evidence(
            "event_probability",
            {"low": 0.8, "base": 0.85, "high": 0.9},
            **probability,
        ),
        _evidence(
            "eligibility_probability",
            {"low": 0.75, "base": 0.8, "high": 0.9},
            **probability,
        ),
        _evidence(
            "survival_probability",
            {"low": 0.8, "base": 0.9, "high": 0.95},
            **probability,
        ),
        _evidence(
            "conditional_reward_usd",
            {"low": 100, "base": 150, "high": 250},
            **economics,
        ),
        _evidence("hard_cost_usd", {"low": 1, "base": 2, "high": 3}, **economics),
        _evidence("capital_at_risk_usd", {"low": 0, "base": 0, "high": 0}, **economics),
        _evidence(
            "expected_capital_loss_usd",
            {"low": 0, "base": 0, "high": 0},
            **economics,
        ),
        _evidence("liquidity_cost_usd", {"low": 0, "base": 0, "high": 0}, **economics),
        _evidence("total_time_hours", {"low": 1, "base": 2, "high": 3}, **economics),
        _evidence("weekly_maintenance_hours", 1.0, **economics),
        _evidence(
            "project_quality",
            80.0,
            observation_type="derived",
            source_grade="B",
            source_type="quality_model",
            independence_group="quality-model",
        ),
        _evidence("project_failure_risk", "low", **risk),
        _evidence("capital_security_risk", "low", **risk),
        _evidence("eligibility_risk", "low", **risk),
        _evidence("reward_dilution_risk", "low", **risk),
        _evidence("liquidity_risk", "low", **risk),
    ]


def _service(conn, **overrides):
    values = {
        "project_repo": ProjectRepository(conn),
        "opportunity_repo": OpportunityRepository(conn),
        "now_factory": lambda: NOW,
    }
    values.update(overrides)
    return OpportunityService(**values)


def _seed(repo, records):
    for record in records:
        repo.add_evidence(record)


def test_sparse_legacy_project_becomes_shadow_watch_without_mutating_legacy(conn):
    assessment = _service(conn).evaluate("p1")

    assert assessment.model_version == "opportunity-v2.0"
    assert assessment.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.public_label == "WATCH"
    assert assessment.economics is None
    assert assessment.confidence.overall == 0
    row = conn.execute("SELECT score, label FROM projects WHERE id = 'p1'").fetchone()
    assert (row["score"], row["label"]) == (90, "FARM")


def test_complete_verified_evidence_is_actionable_and_persists_one_snapshot(conn):
    service = _service(conn)
    records = _complete_evidence()
    _seed(service.opportunity_repo, records)

    assessment = service.evaluate("p1")

    assert assessment.status == DecisionStatus.ACTIONABLE
    assert assessment.public_label == "FARM"
    assert assessment.expires_at == assessment.scored_at + timedelta(hours=48)
    assert assessment.evidence_ids == tuple(sorted({item.evidence_id for item in records}))
    assert assessment.confidence.event >= 0.70
    assert assessment.confidence.eligibility >= 0.65
    assert assessment.confidence.reward >= 0.50
    assert assessment.confidence.cost >= 0.70
    assert assessment.confidence.risk >= 0.70
    assert assessment.confidence.overall >= 0.65
    assert conn.execute("SELECT COUNT(*) FROM opportunity_assessments").fetchone()[0] == 1
    row = conn.execute("SELECT score, label FROM projects WHERE id = 'p1'").fetchone()
    assert (row["score"], row["label"]) == (90, "FARM")


def test_complete_farm_service_with_false_official_identity_is_blocked(conn):
    service = _service(conn)
    records = [
        item.model_copy(update={"value": False}) if item.factor_key == "official_identity" else item
        for item in _complete_evidence()
    ]
    _seed(service.opportunity_repo, records)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.status == DecisionStatus.BLOCKED
    assert assessment.blocker_codes == ("SAFETY_BLOCK",)


def test_service_threads_one_historical_now_through_all_evidence_checks(conn):
    historical_now = datetime(2024, 1, 15, tzinfo=UTC)
    records = [
        record.model_copy(
            update={
                "observed_at": historical_now - timedelta(days=1),
                "expires_at": historical_now + timedelta(days=1),
            }
        )
        for record in _complete_evidence()
    ]
    service = _service(conn, now_factory=lambda: historical_now)
    _seed(service.opportunity_repo, records)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.scored_at == historical_now
    assert assessment.status == DecisionStatus.ACTIONABLE


def test_service_future_now_excludes_evidence_expired_before_that_instant(conn):
    future_now = NOW + timedelta(days=31)
    service = _service(conn, now_factory=lambda: future_now)
    _seed(service.opportunity_repo, _complete_evidence())

    assessment = service.evaluate("p1", persist=False)

    assert assessment.scored_at == future_now
    assert assessment.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.evidence_ids == ()


@pytest.mark.parametrize("temporal_field", ["observed_at", "effective_at"])
def test_service_excludes_future_evidence_from_all_outputs(conn, temporal_field):
    records = [
        record.model_copy(update={temporal_field: NOW + timedelta(seconds=1)}) for record in _complete_evidence()
    ]
    service = _service(conn, now_factory=lambda: NOW)
    _seed(service.opportunity_repo, records)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.blocker_codes == ()
    assert assessment.event_probability is None
    assert assessment.reward_probability is None
    assert assessment.economics is None
    assert assessment.confidence.overall == 0
    assert assessment.evidence_ids == ()
    assert set(assessment.factor_snapshot["critical_unknowns"]) >= {
        "airdrop_basis",
        "conditional_reward",
        "safety_blocked",
    }


@pytest.mark.parametrize(
    ("required_input", "omitted_factors"),
    [
        (
            "reward_probability",
            {
                "event_probability",
                "eligibility_probability",
                "survival_probability",
                "official_airdrop_statement",
                "distribution_catalyst_3_6m",
                "eligibility_mechanism",
                "multiwallet_policy",
            },
        ),
        ("conditional_reward_usd", {"conditional_reward_usd"}),
        ("hard_cost_usd", {"hard_cost_usd"}),
        ("capital_at_risk_usd", {"capital_at_risk_usd"}),
        ("expected_capital_loss_usd", {"expected_capital_loss_usd"}),
        ("liquidity_cost_usd", {"liquidity_cost_usd"}),
        ("total_time_hours", {"total_time_hours"}),
    ],
)
def test_economics_is_not_called_until_every_required_input_is_known(
    conn, monkeypatch, required_input, omitted_factors
):
    service = _service(conn)
    _seed(
        service.opportunity_repo,
        [item for item in _complete_evidence() if item.factor_key not in omitted_factors],
    )
    calculate = Mock(side_effect=AssertionError("must not calculate partial economics"))
    monkeypatch.setattr("app.opportunity.service.calculate_economics", calculate)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.status == DecisionStatus.INSUFFICIENT_EVIDENCE
    assert assessment.public_label == "WATCH"
    assert assessment.economics is None
    assert required_input in assessment.factor_snapshot["critical_unknowns"]
    calculate.assert_not_called()


def test_explicit_zero_capital_loss_and_liquidity_are_known_inputs(conn):
    service = _service(conn)
    _seed(service.opportunity_repo, _complete_evidence())

    assessment = service.evaluate("p1", persist=False)

    assert assessment.expected_capital_loss_usd.base == 0
    assert assessment.liquidity_cost_usd.base == 0
    assert assessment.economics is not None


def test_missing_capital_at_risk_never_defaults_to_zero(conn, monkeypatch):
    service = _service(conn)
    _seed(
        service.opportunity_repo,
        [item for item in _complete_evidence() if item.factor_key != "capital_at_risk_usd"],
    )
    calculate = Mock(side_effect=AssertionError("missing capital exposure must stop economics"))
    monkeypatch.setattr("app.opportunity.service.calculate_economics", calculate)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.economics is None
    assert "capital_at_risk_usd" in assessment.factor_snapshot["critical_unknowns"]
    calculate.assert_not_called()


def test_assumed_economics_do_not_receive_direct_evidence_confidence(conn):
    assumed_factors = {
        "conditional_reward_usd",
        "hard_cost_usd",
        "expected_capital_loss_usd",
        "liquidity_cost_usd",
        "total_time_hours",
    }
    records = [
        item.model_copy(update={"observation_type": "assumed"}) if item.factor_key in assumed_factors else item
        for item in _complete_evidence()
    ]
    service = _service(conn)
    _seed(service.opportunity_repo, records)

    assessment = service.evaluate("p1", persist=False)

    assert assessment.public_label == "WATCH"
    assert "economics_direct_evidence" in assessment.factor_snapshot["critical_unknowns"]


def test_factor_snapshot_is_exact_whitelist_and_contains_no_evidence_metadata(conn):
    service = _service(conn)
    _seed(service.opportunity_repo, _complete_evidence())

    assessment = service.evaluate("p1", persist=False)
    serialized = assessment.model_dump(mode="json")["factor_snapshot"]

    assert set(serialized) == SNAPSHOT_KEYS
    snapshot_text = assessment.model_dump_json()
    assert "https://" not in snapshot_text
    assert "raw/" not in snapshot_text
    assert "Legacy Alpha" not in snapshot_text
    assert "e-official_identity" not in str(serialized)


def test_assessment_snapshot_and_nested_values_are_immutable(conn):
    service = _service(conn)
    _seed(service.opportunity_repo, _complete_evidence())
    assessment = service.evaluate("p1", persist=False)

    assert isinstance(assessment.factor_snapshot, MappingProxyType)
    with pytest.raises(TypeError):
        assessment.factor_snapshot["project_quality"] = 0
    with pytest.raises(ValidationError):
        assessment.public_label = "IGNORE"


def test_evidence_ids_are_sorted_unique_even_if_repository_returns_duplicates(conn):
    records = list(reversed(_complete_evidence()))
    opportunity_repo = Mock()
    opportunity_repo.list_evidence.return_value = [*records, records[0]]
    service = _service(conn, opportunity_repo=opportunity_repo)

    assessment = service.evaluate_row({"id": "p1"}, persist=False)

    assert assessment.evidence_ids == tuple(sorted({item.evidence_id for item in records}))
    opportunity_repo.save_assessment.assert_not_called()


def test_evaluate_persists_exactly_once_and_persist_false_never_writes(conn):
    project_repo = Mock()
    project_repo.get_by_id.return_value = {"id": "p1", "score": 90, "label": "FARM"}
    opportunity_repo = Mock()
    opportunity_repo.list_evidence.return_value = []
    opportunity_repo.save_assessment.side_effect = lambda assessment: assessment.model_copy(
        update={"assessment_id": "persisted-assessment"}
    )
    service = OpportunityService(
        project_repo=project_repo,
        opportunity_repo=opportunity_repo,
        now_factory=lambda: NOW,
    )

    first = service.evaluate("p1")
    second = service.evaluate("p1", persist=False)

    opportunity_repo.save_assessment.assert_called_once()
    pending = opportunity_repo.save_assessment.call_args.args[0]
    assert pending.assessment_id is None
    assert first.assessment_id == "persisted-assessment"
    assert second.assessment_id is None


def test_missing_project_raises_lookup_error_without_persistence(conn):
    project_repo = Mock()
    project_repo.get_by_id.return_value = None
    opportunity_repo = Mock()
    service = OpportunityService(project_repo=project_repo, opportunity_repo=opportunity_repo)

    with pytest.raises(LookupError, match="missing"):
        service.evaluate("missing")

    opportunity_repo.list_evidence.assert_not_called()
    opportunity_repo.save_assessment.assert_not_called()


def test_unexpected_repository_exception_is_not_caught(conn):
    project_repo = Mock()
    project_repo.get_by_id.side_effect = RuntimeError("database unavailable")
    service = OpportunityService(project_repo=project_repo, opportunity_repo=Mock())

    with pytest.raises(RuntimeError, match="database unavailable"):
        service.evaluate("p1")


def test_service_does_not_close_injected_repositories(conn):
    project_repo = Mock()
    opportunity_repo = Mock()
    service = OpportunityService(project_repo=project_repo, opportunity_repo=opportunity_repo)

    service.close()

    project_repo.close.assert_not_called()
    opportunity_repo.close.assert_not_called()


def test_falsey_injected_repositories_are_preserved():
    class FalseyRepository(Mock):
        def __bool__(self):
            return False

    project_repo = FalseyRepository()
    opportunity_repo = FalseyRepository()

    service = OpportunityService(
        project_repo=project_repo,
        opportunity_repo=opportunity_repo,
    )

    assert service.project_repo is project_repo
    assert service.opportunity_repo is opportunity_repo


def test_context_closes_owned_opportunity_repository(monkeypatch):
    owned = Mock()
    monkeypatch.setattr("app.opportunity.service.OpportunityRepository", lambda: owned)

    with OpportunityService(project_repo=Mock()) as service:
        assert service.opportunity_repo is owned
        owned.close.assert_not_called()

    owned.close.assert_called_once_with()


def _confidence_for(records):
    inputs = build_inputs({"id": "p1", "meta": "{}"}, records, DEFAULT_PROFILE, now=NOW)
    return _build_confidence(inputs, records, NOW)


def _cost_records(**overrides):
    values = {
        "hard_cost_usd": {"low": 1, "base": 2, "high": 3},
        "capital_at_risk_usd": {"low": 0, "base": 0, "high": 0},
        "expected_capital_loss_usd": {"low": 0, "base": 0, "high": 0},
        "liquidity_cost_usd": {"low": 0, "base": 0, "high": 0},
        "total_time_hours": {"low": 1, "base": 2, "high": 3},
        "weekly_maintenance_hours": 1.0,
    }
    return [_evidence(factor, value, **overrides) for factor, value in values.items()]


def test_confidence_source_reliability_is_average_resolved_grade_weight():
    confidence = _confidence_for(_cost_records(source_grade="B"))
    assert confidence.cost == pytest.approx(0.35 * 0.8 + 0.25 + 0.15 + 0.25)


def test_confidence_coverage_is_required_factor_fraction_only():
    confidence = _confidence_for(_cost_records()[:1])
    assert confidence.cost == pytest.approx(0.35 + 0.25 * 0.2 + 0.15 + 0.25)


def test_confidence_independence_uses_distinct_groups_over_resolved_records():
    confidence = _confidence_for(_cost_records(independence_group="shared-source"))
    assert confidence.cost == pytest.approx(0.35 + 0.25 + 0.15 * 0.2 + 0.25)


@pytest.mark.parametrize(
    ("age", "expected_freshness"),
    [(7, 1.0), (30, 0.8), (90, 0.5), (91, 0.2)],
)
def test_confidence_freshness_uses_exact_age_bands(age, expected_freshness):
    records = _cost_records(
        observed_at=NOW - timedelta(days=age),
        expires_at=NOW + timedelta(days=1),
    )
    confidence = _confidence_for(records)
    assert confidence.cost == pytest.approx(0.35 + 0.25 + 0.15 + 0.25 * expected_freshness)


def test_lower_grade_superseded_conflict_halves_domain_freshness_consistency():
    records = _cost_records()
    records.append(
        _evidence(
            "hard_cost_usd",
            {"low": 5, "base": 6, "high": 7},
            evidence_id="old-lower-grade-conflict",
            source_grade="B",
            observed_at=NOW - timedelta(days=2),
        )
    )
    confidence = _confidence_for(records)
    assert confidence.cost == pytest.approx(0.35 + 0.25 + 0.15 + 0.25 * 0.9)


def test_unresolved_conflict_removes_factor_and_has_zero_factor_consistency():
    records = _cost_records()
    records.append(
        _evidence(
            "hard_cost_usd",
            {"low": 5, "base": 6, "high": 7},
            evidence_id="same-grade-conflict",
        )
    )
    confidence = _confidence_for(records)
    assert confidence.cost == pytest.approx(0.35 + 0.25 * 0.8 + 0.15 + 0.25)


def test_partially_verified_evidence_does_not_contribute_to_confidence():
    confidence = _confidence_for(_cost_records(verification_status="partially_verified"))
    assert confidence.cost == 0


def test_cross_project_evidence_does_not_contribute_to_confidence():
    confidence = _confidence_for(_cost_records(project_id="p2"))
    assert confidence.cost == 0
