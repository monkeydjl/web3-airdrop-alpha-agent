import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.db import DbConnection, _postgres_ddl, init_db
from app.opportunity.models import EvidenceRecord, OpportunityAssessment
from app.opportunity.repository import OpportunityRepository

NOW = datetime(2026, 7, 14, tzinfo=UTC)


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def test_postgres_interactions_ddl_has_exact_outcome_column_types():
    ddl = _postgres_ddl()
    expected = (
        "wallet_cohort_id TEXT",
        "wallet_count INTEGER DEFAULT 1",
        "actual_hard_cost_usd DOUBLE PRECISION",
        "actual_time_minutes INTEGER",
        "eligibility_result TEXT",
        "survival_result TEXT",
        "disqualification_reason TEXT",
        "reward_received_usd DOUBLE PRECISION",
        "claim_cost_usd DOUBLE PRECISION",
        "opportunity_assessment_id TEXT",
        "opportunity_model_version TEXT",
        "opportunity_profile_version TEXT",
        "outcome_observed_at TIMESTAMPTZ",
    )
    normalized = " ".join(ddl.split())
    for definition in expected:
        assert definition in normalized


def _evidence(**overrides) -> EvidenceRecord:
    data = {
        "project_id": "p1",
        "factor_key": "official_points_program",
        "value": {"confirmed": True, "tiers": [1, 2], "label": "积分"},
        "value_type": "json",
        "observation_type": "observed",
        "source_url": "https://project.example/docs/points",
        "source_type": "official_docs",
        "source_grade": "A",
        "observed_at": NOW,
        "verification_status": "verified",
        "independence_group": "official-docs-points",
    }
    data.update(overrides)
    return EvidenceRecord(**data)


@pytest.mark.parametrize(
    "query_key",
    [
        "token",
        "access_token",
        "refresh_token",
        "id_token",
        "security_token",
        "session_token",
        "auth_token",
        "api_key",
        "x-api-key",
        "client_secret",
        "api_secret",
        "app_secret",
        "access_key",
        "access_key_id",
        "aws_access_key_id",
        "private_key",
        "credential",
        "credentials",
        "X-Amz-Credential",
        "signature",
        "X-Amz-Signature",
        "password",
        "passwd",
        "authorization",
        "auth",
        "jwt",
        "session",
        "session_id",
        "sig",
        "key",
        "secret",
    ],
)
def test_repository_rejects_sensitive_url_query_keys_even_for_unvalidated_model(query_key):
    raw = _connection()
    repository = OpportunityRepository(raw)
    record = _evidence().model_copy(update={"source_url": f"https://project.example/docs?{query_key}=value"})

    with pytest.raises(ValueError, match="sensitive query keys"):
        repository.add_evidence(record)

    assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
    raw.close()


def _assessment(scored_at: datetime, action: str) -> OpportunityAssessment:
    return OpportunityAssessment(
        project_id="p1",
        model_version="opportunity-v2.0",
        profile_version="low-cost-curated-multiwallet-v1",
        risks={
            "capital_security": "low",
            "eligibility": "medium",
            "project_failure": "medium",
            "reward_dilution": "high",
            "liquidity": "low",
        },
        confidence={
            "event": 0.8,
            "eligibility": 0.7,
            "reward": 0.6,
            "cost": 0.9,
            "risk": 0.75,
            "quality": 0.65,
            "overall": 0.7,
        },
        status="MONITOR",
        public_label="WATCH",
        recommended_action=action,
        factor_snapshot={"policy": {"status": "unknown"}, "sources": ["docs"]},
        scored_at=scored_at,
        review_at=scored_at + timedelta(days=7),
        expires_at=scored_at + timedelta(days=30),
    )


def _fully_populated_assessment(**overrides) -> OpportunityAssessment:
    data = {
        **_assessment(NOW, "Proceed with the monitored plan.").model_dump(mode="json"),
        "event_probability": {"low": 0.5, "base": 0.7, "high": 0.9},
        "eligibility_probability": {"low": 0.4, "base": 0.6, "high": 0.8},
        "survival_probability": {"low": 0.6, "base": 0.75, "high": 0.9},
        "reward_probability": {"low": 0.2, "base": 0.35, "high": 0.5},
        "conditional_reward_usd": {"low": 50, "base": 100, "high": 250},
        "hard_cost_usd": {"low": 2, "base": 5, "high": 10},
        "expected_capital_loss_usd": {"low": 0, "base": 3, "high": 12},
        "liquidity_cost_usd": {"low": 1, "base": 2, "high": 4},
        "total_time_hours": {"low": 3, "base": 6, "high": 12},
        "weekly_maintenance_hours": 1.5,
        "economics": {
            "gross_reward": {"low": 10, "base": 35, "high": 112.5},
            "net_reward": {"low": -16, "base": 25, "high": 109.5},
            "reward_to_cost_ratio": 4.2,
            "decision_value": 28.75,
            "capital_efficiency": 5.75,
            "time_efficiency": 4.79,
        },
        "project_quality": 67.5,
        "blocker_codes": ("blocker-a",),
        "watch_reason_codes": ("watch-a", "watch-b"),
        "ignore_reason_codes": ("ignore-a",),
        "evidence_ids": ("evidence-a", "evidence-b"),
        "factor_snapshot": {
            "policy": {"status": "allowed"},
            "weights": [0.1, 0.2],
            "unicode": "证据",
        },
    }
    data.update(overrides)
    return OpportunityAssessment(**data)


class _PoisonAfterIntegrityError(DbConnection):
    def __init__(self, raw: sqlite3.Connection):
        super().__init__(raw, kind="sqlite")
        self.poisoned = False

    def execute(self, sql, params=None):
        if self.poisoned:
            raise sqlite3.OperationalError("transaction remains aborted")
        try:
            return super().execute(sql, params)
        except sqlite3.IntegrityError:
            self.poisoned = True
            raise

    def rollback(self):
        super().rollback()
        self.poisoned = False


def _poisonable_connection() -> tuple[sqlite3.Connection, _PoisonAfterIntegrityError]:
    raw = _connection()
    return raw, _PoisonAfterIntegrityError(raw)


def test_init_db_creates_idempotent_opportunity_schema_without_foreign_keys():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row

    init_db(conn)
    init_db(conn)

    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    indexes = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"opportunity_evidence", "opportunity_assessments"} <= tables
    assert {
        "idx_opportunity_evidence_project",
        "idx_opportunity_evidence_factor",
        "idx_opportunity_assessment_latest",
        "idx_opportunity_assessment_label",
    } <= indexes
    assert list(conn.execute("PRAGMA foreign_key_list(opportunity_evidence)")) == []
    assert list(conn.execute("PRAGMA foreign_key_list(opportunity_assessments)")) == []
    conn.close()


def test_postgres_ddl_defines_equivalent_opportunity_schema_without_foreign_keys():
    ddl = _postgres_ddl().lower()

    assert "create table if not exists opportunity_evidence" in ddl
    assert "create table if not exists opportunity_assessments" in ddl
    assert "decision_value     double precision" in ddl
    assert "idx_opportunity_assessment_latest" in ddl
    assert "foreign key" not in ddl
    assert " references " not in ddl
    for column in ("observed_at", "effective_at", "expires_at", "created_at", "scored_at", "review_at"):
        assert f"{column}" in ddl
    evidence_ddl = ddl.split("create table if not exists opportunity_evidence", 1)[1].split(");", 1)[0]
    assessment_ddl = ddl.split("create table if not exists opportunity_assessments", 1)[1].split(");", 1)[0]
    assert " timestamp " not in evidence_ddl.replace("current_timestamp", "")
    assert " timestamp " not in assessment_ddl.replace("current_timestamp", "")


def test_evidence_is_append_only_and_json_round_trips():
    conn = _connection()
    repo = OpportunityRepository(conn)
    record = _evidence()

    first = repo.add_evidence(record)
    second = repo.add_evidence(record)
    loaded = repo.list_evidence("p1")

    assert first.evidence_id != second.evidence_id
    assert {item.evidence_id for item in loaded} == {
        first.evidence_id,
        second.evidence_id,
    }
    assert loaded[0].value == record.value
    assert loaded[0].model_dump(mode="json")["value"] == {
        "confirmed": True,
        "tiers": [1, 2],
        "label": "积分",
    }
    assert record.evidence_id is None
    conn.close()


def test_generated_and_supplied_evidence_ids_are_preserved_uuid4_values():
    conn = _connection()
    repo = OpportunityRepository(conn)

    generated = repo.add_evidence(_evidence())
    supplied = repo.add_evidence(_evidence(evidence_id="evidence-supplied"))

    assert uuid.UUID(generated.evidence_id).version == 4
    assert supplied.evidence_id == "evidence-supplied"
    conn.close()


def test_duplicate_evidence_id_rolls_back_before_next_write():
    raw, conn = _poisonable_connection()
    repo = OpportunityRepository(conn)
    duplicate = _evidence(evidence_id="duplicate-evidence")

    repo.add_evidence(duplicate)
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_evidence(duplicate)

    stored = repo.add_evidence(_evidence(evidence_id="evidence-after-failure"))
    assert stored.evidence_id == "evidence-after-failure"
    assert conn.poisoned is False
    raw.close()


def test_list_evidence_excludes_invalid_by_default():
    conn = _connection()
    repo = OpportunityRepository(conn)
    valid = repo.add_evidence(_evidence())
    invalid = repo.add_evidence(_evidence(verification_status="invalidated"))

    assert [item.evidence_id for item in repo.list_evidence("p1")] == [valid.evidence_id]
    assert {item.evidence_id for item in repo.list_evidence("p1", include_invalid=True)} == {
        valid.evidence_id,
        invalid.evidence_id,
    }
    conn.close()


def test_repository_validates_supersession_target_same_project_and_factor():
    conn = _connection()
    conn.execute("INSERT INTO projects (id, name) VALUES (?, ?)", ("p2", "Other"))
    conn.commit()
    repo = OpportunityRepository(conn)
    target = repo.add_evidence(
        _evidence(evidence_id="target", factor_key="safety_blocked", value=True, value_type="bool")
    )

    stored = repo.add_evidence(
        _evidence(
            evidence_id="valid-remediation",
            factor_key="safety_blocked",
            value=False,
            value_type="bool",
            supersedes_evidence_id=target.evidence_id,
        )
    )
    assert stored.supersedes_evidence_id == "target"
    with pytest.raises(ValueError, match="same project and factor"):
        repo.add_evidence(
            _evidence(
                evidence_id="wrong-factor",
                factor_key="integrity_blocked",
                value=False,
                value_type="bool",
                supersedes_evidence_id="target",
            )
        )
    with pytest.raises(ValueError, match="existing"):
        repo.add_evidence(
            _evidence(
                evidence_id="missing-target",
                factor_key="safety_blocked",
                value=False,
                value_type="bool",
                supersedes_evidence_id="missing",
            )
        )
    assert len(repo.list_evidence("p1", include_invalid=True)) == 2
    conn.close()


def test_repository_rejects_backdated_supersession_and_rolls_back():
    conn = _connection()
    repo = OpportunityRepository(conn)
    repo.add_evidence(
        _evidence(
            evidence_id="newer-target",
            factor_key="safety_blocked",
            value=True,
            value_type="bool",
            observed_at=NOW,
        )
    )

    with pytest.raises(ValueError, match="chronological"):
        repo.add_evidence(
            _evidence(
                evidence_id="backdated",
                factor_key="safety_blocked",
                value=False,
                value_type="bool",
                observed_at=NOW - timedelta(seconds=1),
                supersedes_evidence_id="newer-target",
            )
        )

    assert [item.evidence_id for item in repo.list_evidence("p1")] == ["newer-target"]
    conn.close()


def test_repository_rejects_supersession_cycle_in_existing_chain():
    conn = _connection()
    repo = OpportunityRepository(conn)
    repo.add_evidence(
        _evidence(
            evidence_id="first",
            factor_key="safety_blocked",
            value=True,
            value_type="bool",
        )
    )
    repo.add_evidence(
        _evidence(
            evidence_id="second",
            factor_key="safety_blocked",
            value=True,
            value_type="bool",
            supersedes_evidence_id="first",
        )
    )
    conn.execute(
        "UPDATE opportunity_evidence SET supersedes_evidence_id = ? WHERE evidence_id = ?",
        ("pending", "first"),
    )
    conn.commit()

    with pytest.raises(ValueError, match="cycle"):
        repo.add_evidence(
            _evidence(
                evidence_id="pending",
                factor_key="safety_blocked",
                value=False,
                value_type="bool",
                supersedes_evidence_id="second",
            )
        )
    conn.close()


def test_repository_accepts_chronological_chain_and_branching_edges():
    conn = _connection()
    repo = OpportunityRepository(conn)
    repo.add_evidence(
        _evidence(
            evidence_id="root",
            factor_key="safety_blocked",
            value=True,
            value_type="bool",
            observed_at=NOW,
        )
    )
    for evidence_id, target, observed_at in (
        ("confirmation", "root", NOW + timedelta(minutes=1)),
        ("branch", "root", NOW + timedelta(minutes=2)),
        ("tip", "confirmation", NOW + timedelta(minutes=3)),
    ):
        repo.add_evidence(
            _evidence(
                evidence_id=evidence_id,
                factor_key="safety_blocked",
                value=evidence_id != "tip",
                value_type="bool",
                observed_at=observed_at,
                supersedes_evidence_id=target,
            )
        )

    assert {item.evidence_id for item in repo.list_evidence("p1")} == {"root", "confirmation", "branch", "tip"}
    conn.close()


@pytest.mark.parametrize(
    "source_url",
    [
        "https://project.example/docs#fragment",
        "https://user@project.example/docs",
        "https://project.example/docs?access_token=value",
        "https://project.example/docs?api-key=value",
        "https://project.example/docs?password=value",
    ],
)
def test_repository_boundary_rejects_unsafe_source_urls(source_url):
    conn = _connection()
    repo = OpportunityRepository(conn)

    with pytest.raises(ValueError):
        repo.add_evidence(_evidence().model_copy(update={"source_url": source_url}))

    assert repo.list_evidence("p1", include_invalid=True) == []
    conn.close()


def test_assessments_are_append_only_and_latest_uses_scored_at():
    conn = _connection()
    repo = OpportunityRepository(conn)
    first = _assessment(NOW, "Wait for more evidence.")
    second = _assessment(NOW + timedelta(hours=1), "Review updated evidence.")

    first_saved = repo.save_assessment(first)
    second_saved = repo.save_assessment(second)
    latest = repo.latest_assessment("p1", "low-cost-curated-multiwallet-v1")

    rows = list(conn.execute("SELECT assessment_id, assessment_json FROM opportunity_assessments"))
    assert first_saved.assessment_id != second_saved.assessment_id
    assert len(rows) == 2
    assert latest is not None
    assert latest.assessment_id == second_saved.assessment_id
    assert latest == second_saved
    assert latest.recommended_action == "Review updated evidence."
    assert latest.factor_snapshot == second.factor_snapshot
    assert first.assessment_id is None
    assert second.assessment_id is None
    conn.close()


def test_generated_and_supplied_assessment_ids_are_preserved_uuid4_values():
    conn = _connection()
    repo = OpportunityRepository(conn)

    generated = repo.save_assessment(_assessment(NOW, "Generated ID"))
    supplied = repo.save_assessment(
        _assessment(NOW + timedelta(hours=1), "Supplied ID").model_copy(update={"assessment_id": "assessment-supplied"})
    )

    assert generated.assessment_id is not None
    assert uuid.UUID(generated.assessment_id).version == 4
    assert supplied.assessment_id == "assessment-supplied"
    conn.close()


def test_duplicate_assessment_id_rolls_back_before_next_write():
    raw, conn = _poisonable_connection()
    repo = OpportunityRepository(conn)
    duplicate = _assessment(NOW, "Duplicate").model_copy(update={"assessment_id": "duplicate-assessment"})

    repo.save_assessment(duplicate)
    with pytest.raises(sqlite3.IntegrityError):
        repo.save_assessment(duplicate)

    saved = repo.save_assessment(
        _assessment(NOW + timedelta(hours=1), "After failure").model_copy(
            update={"assessment_id": "assessment-after-failure"}
        )
    )
    assert saved.assessment_id == "assessment-after-failure"
    assert conn.poisoned is False
    raw.close()


def test_fully_populated_assessment_round_trips_with_model_equality():
    conn = _connection()
    repo = OpportunityRepository(conn)
    assessment = _fully_populated_assessment()

    saved = repo.save_assessment(assessment)
    loaded = repo.latest_assessment("p1", "low-cost-curated-multiwallet-v1")

    assert loaded == saved
    conn.close()


def test_blocked_remediation_flag_round_trips_through_repository():
    conn = _connection()
    repo = OpportunityRepository(conn)
    assessment = _fully_populated_assessment(
        status="BLOCKED",
        public_label="IGNORE",
        requires_remediation=True,
        blocker_codes=("SAFETY_BLOCK",),
    )

    saved = repo.save_assessment(assessment)
    loaded = repo.latest_assessment("p1", "low-cost-curated-multiwallet-v1")

    assert loaded == saved
    assert loaded is not None
    assert loaded.requires_remediation is True
    conn.close()


def test_latest_assessment_breaks_scored_at_tie_with_created_at():
    conn = _connection()
    repo = OpportunityRepository(conn)
    first = repo.save_assessment(_assessment(NOW, "Created first"))
    second = repo.save_assessment(_assessment(NOW, "Created second"))
    conn.execute(
        "UPDATE opportunity_assessments SET created_at = ? WHERE assessment_id = ?",
        ("2026-07-14T00:00:00+00:00", first.assessment_id),
    )
    conn.execute(
        "UPDATE opportunity_assessments SET created_at = ? WHERE assessment_id = ?",
        ("2026-07-14T00:00:01+00:00", second.assessment_id),
    )
    conn.commit()

    latest = repo.latest_assessment("p1", "low-cost-curated-multiwallet-v1")

    assert latest is not None
    assert latest.assessment_id == second.assessment_id
    conn.close()


def test_latest_assessment_breaks_complete_tie_with_assessment_id_desc():
    conn = _connection()
    repo = OpportunityRepository(conn)
    for assessment_id in ("assessment-a", "assessment-z"):
        repo.save_assessment(_assessment(NOW, assessment_id).model_copy(update={"assessment_id": assessment_id}))
    conn.execute("UPDATE opportunity_assessments SET created_at = ?", ("2026-07-14T00:00:00Z",))
    conn.commit()

    latest = repo.latest_assessment("p1", "low-cost-curated-multiwallet-v1")

    assert latest is not None
    assert latest.assessment_id == "assessment-z"
    conn.close()


def test_repository_context_does_not_close_borrowed_connection():
    conn = _connection()

    with OpportunityRepository(conn) as repo:
        repo.add_evidence(_evidence())

    assert conn.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 1
    conn.close()


def test_repository_context_closes_owned_connection(monkeypatch):
    raw = _connection()
    owned = DbConnection(raw, kind="sqlite")
    monkeypatch.setattr("app.db.get_connection", lambda: owned)

    with OpportunityRepository() as repo:
        repo.add_evidence(_evidence())

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        raw.execute("SELECT 1")


def test_latest_assessment_returns_none_when_absent():
    conn = _connection()

    assert OpportunityRepository(conn).latest_assessment("missing", "low-cost-curated-multiwallet-v1") is None
    conn.close()
