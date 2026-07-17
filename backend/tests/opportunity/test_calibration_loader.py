import sqlite3
from datetime import UTC, datetime, timedelta
from types import MappingProxyType

from app.db import init_db
from app.opportunity.calibration import RangeValue, load_calibration_dataset
from app.opportunity.models import OpportunityAssessment

MODEL_VERSION = "opportunity-v2.0"
PROFILE_VERSION = "low-cost-curated-multiwallet-v1"
SCORED_AT = datetime(2026, 1, 1, tzinfo=UTC)
OBSERVED_AT = datetime(2026, 4, 1, tzinfo=UTC)
QUALITY_KEYS = {
    "missing_linkage",
    "mismatched_project",
    "unsupported_version",
    "missing_or_invalid_cohort",
    "malformed_assessment_json",
    "invalid_timestamp",
    "duplicate_pair",
}


def _cohort(number: int) -> str:
    return f"cohort-550e8400-e29b-41d4-a716-44665544{number:04x}"


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _assessment(**updates) -> OpportunityAssessment:
    values = {
        "assessment_id": "assessment-1",
        "project_id": "project-1",
        "model_version": MODEL_VERSION,
        "profile_version": PROFILE_VERSION,
        "event_probability": {"low": 0.5, "base": 0.7, "high": 0.9},
        "eligibility_probability": {"low": 0.4, "base": 0.6, "high": 0.8},
        "survival_probability": {"low": 0.6, "base": 0.75, "high": 0.9},
        "reward_probability": {"low": 0.2, "base": 0.35, "high": 0.5},
        "conditional_reward_usd": {"low": 50, "base": 100, "high": 250},
        "hard_cost_usd": {"low": 2, "base": 5, "high": 10},
        "total_time_hours": {"low": 3, "base": 6, "high": 12},
        "economics": {
            "gross_reward": {"low": 10, "base": 35, "high": 112.5},
            "net_reward": {"low": -16, "base": 25, "high": 109.5},
            "reward_to_cost_ratio": 4.2,
            "decision_value": 28.75,
            "capital_efficiency": 5.75,
            "time_efficiency": 4.79,
        },
        "risks": {},
        "confidence": {
            "event": 0.8,
            "eligibility": 0.7,
            "reward": 0.6,
            "cost": 0.9,
            "risk": 0.75,
            "quality": 0.65,
            "overall": 0.7,
        },
        "status": "ACTIONABLE",
        "public_label": "FARM",
        "recommended_action": "Proceed.",
        "scored_at": SCORED_AT,
        "review_at": SCORED_AT + timedelta(days=7),
        "expires_at": SCORED_AT + timedelta(days=30),
    }
    values.update(updates)
    return OpportunityAssessment(**values)


def _insert_assessment(conn: sqlite3.Connection, assessment: OpportunityAssessment) -> None:
    conn.execute(
        """
        INSERT INTO opportunity_assessments (
            assessment_id, project_id, model_version, profile_version,
            assessment_json, decision_status, public_label,
            overall_confidence, scored_at, review_at, expires_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            assessment.assessment_id,
            assessment.project_id,
            assessment.model_version,
            assessment.profile_version,
            assessment.model_dump_json(),
            assessment.status,
            assessment.public_label,
            assessment.confidence.overall,
            assessment.scored_at.isoformat(),
            assessment.review_at.isoformat(),
            assessment.expires_at.isoformat(),
        ),
    )


def _insert_interaction(conn: sqlite3.Connection, **updates) -> None:
    values = {
        "project_id": "project-1",
        "wallet_cohort_id": _cohort(1),
        "wallet_count": 3,
        "actual_hard_cost_usd": 6.5,
        "actual_time_minutes": 150,
        "eligibility_result": None,
        "survival_result": "passed",
        "reward_received_usd": None,
        "claim_cost_usd": 1.25,
        "opportunity_assessment_id": "assessment-1",
        "opportunity_model_version": MODEL_VERSION,
        "opportunity_profile_version": PROFILE_VERSION,
        "outcome_observed_at": OBSERVED_AT.isoformat(),
        "outcome": None,
    }
    values.update(updates)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    conn.execute(
        f"INSERT INTO interactions ({columns}) VALUES ({placeholders})",  # noqa: S608 -- trusted test columns
        tuple(values.values()),
    )


class RecordingConnection:
    kind = "sqlite"

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.statements: list[str] = []

    def execute(self, sql, params=None):
        self.statements.append(sql)
        if params is None:
            return self.connection.execute(sql)
        return self.connection.execute(sql, params)


def test_loader_builds_explicit_assessment_cohort_sample():
    conn = _connection()
    assessment = _assessment()
    _insert_assessment(conn, assessment)
    _insert_interaction(conn)
    conn.commit()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert dataset.backend == "sqlite"
    assert len(dataset.samples) == 1
    sample = dataset.samples[0]
    assert (sample.project_id, sample.assessment_id, sample.cohort_id) == (
        "project-1",
        "assessment-1",
        _cohort(1),
    )
    assert sample.event_probability == RangeValue(0.5, 0.7, 0.9)
    assert sample.eligibility_probability == RangeValue(0.4, 0.6, 0.8)
    assert sample.survival_probability == RangeValue(0.6, 0.75, 0.9)
    assert sample.reward_probability == RangeValue(0.2, 0.35, 0.5)
    assert sample.net_reward == RangeValue(-16, 25, 109.5)
    assert sample.hard_cost == RangeValue(2, 5, 10)
    assert sample.total_time_hours == RangeValue(3, 6, 12)
    assert sample.outcome is None
    assert sample.eligibility_result is None
    assert sample.reward_received_usd is None
    assert sample.actual_hard_cost_usd == 6.5
    assert sample.claim_cost_usd == 1.25
    assert sample.actual_time_minutes == 150
    conn.close()


def test_loader_accounts_for_every_exclusion_and_excludes_all_duplicate_members():
    conn = _connection()
    for number in range(1, 9):
        assessment = _assessment(
            assessment_id=f"assessment-{number}",
            project_id=f"project-{number}",
        )
        _insert_assessment(conn, assessment)

    conn.execute(
        "UPDATE opportunity_assessments SET assessment_json = ? WHERE assessment_id = ?",
        ("{malformed", "assessment-5"),
    )
    _insert_interaction(
        conn,
        project_id="project-missing",
        opportunity_assessment_id="does-not-exist",
        wallet_cohort_id=_cohort(2),
    )
    _insert_interaction(
        conn,
        project_id="wrong-project",
        opportunity_assessment_id="assessment-2",
        wallet_cohort_id=_cohort(3),
    )
    _insert_interaction(
        conn,
        project_id="project-3",
        opportunity_assessment_id="assessment-3",
        opportunity_model_version="opportunity-v1.0",
        wallet_cohort_id=_cohort(4),
    )
    _insert_interaction(
        conn,
        project_id="project-4",
        opportunity_assessment_id="assessment-4",
        wallet_cohort_id="cohort-not-a-uuid",
    )
    _insert_interaction(
        conn,
        project_id="project-5",
        opportunity_assessment_id="assessment-5",
        wallet_cohort_id=_cohort(5),
    )
    _insert_interaction(
        conn,
        project_id="project-6",
        opportunity_assessment_id="assessment-6",
        wallet_cohort_id=_cohort(6),
        outcome_observed_at="not-a-timestamp",
    )
    for outcome in ("airdropped", "not_airdropped"):
        _insert_interaction(
            conn,
            project_id="project-7",
            opportunity_assessment_id="assessment-7",
            wallet_cohort_id=_cohort(7),
            outcome=outcome,
        )
    _insert_interaction(
        conn,
        project_id="project-8",
        opportunity_assessment_id="assessment-8",
        wallet_cohort_id=_cohort(8),
    )
    conn.commit()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert [(sample.assessment_id, sample.cohort_id) for sample in dataset.samples] == [("assessment-8", _cohort(8))]
    assert dataset.quality == {
        "missing_linkage": 1,
        "mismatched_project": 1,
        "unsupported_version": 1,
        "missing_or_invalid_cohort": 1,
        "malformed_assessment_json": 1,
        "invalid_timestamp": 1,
        "duplicate_pair": 2,
    }
    assert set(dataset.quality) == QUALITY_KEYS
    assert all(not isinstance(value, (tuple, list, set, dict)) for value in dataset.quality.values())
    conn.close()


def test_loader_sorts_samples_and_reports_zero_quality_counts():
    conn = _connection()
    for assessment_id, project_id, cohort_id in (
        ("assessment-z", "project-b", _cohort(12)),
        ("assessment-b", "project-a", _cohort(11)),
        ("assessment-a", "project-a", _cohort(10)),
    ):
        _insert_assessment(
            conn,
            _assessment(assessment_id=assessment_id, project_id=project_id),
        )
        _insert_interaction(
            conn,
            project_id=project_id,
            opportunity_assessment_id=assessment_id,
            wallet_cohort_id=cohort_id,
        )
    conn.commit()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert [(sample.project_id, sample.assessment_id, sample.cohort_id) for sample in dataset.samples] == [
        ("project-a", "assessment-a", _cohort(10)),
        ("project-a", "assessment-b", _cohort(11)),
        ("project-b", "assessment-z", _cohort(12)),
    ]
    assert dataset.quality == dict.fromkeys(QUALITY_KEYS, 0)
    conn.close()


def test_loader_executes_only_the_two_selects():
    conn = _connection()
    _insert_assessment(conn, _assessment())
    _insert_interaction(conn)
    conn.commit()
    recording = RecordingConnection(conn)

    load_calibration_dataset(
        recording,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert len(recording.statements) == 2
    assert all(statement.lstrip().upper().startswith("SELECT") for statement in recording.statements)
    conn.close()


def test_loader_rejects_timezone_naive_timestamps():
    conn = _connection()
    _insert_assessment(conn, _assessment())
    _insert_interaction(conn, outcome_observed_at="2026-04-01T00:00:00")
    conn.commit()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert dataset.samples == ()
    assert dataset.quality["invalid_timestamp"] == 1
    conn.close()


def test_loader_returns_immutable_quality_mapping():
    conn = _connection()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert isinstance(dataset.quality, MappingProxyType)
    conn.close()


def test_loader_excludes_every_duplicate_member_before_other_validation():
    conn = _connection()
    _insert_assessment(conn, _assessment())
    _insert_interaction(conn)
    _insert_interaction(conn, outcome_observed_at="not-a-timestamp")
    conn.commit()

    dataset = load_calibration_dataset(
        conn,
        model_version=MODEL_VERSION,
        profile_version=PROFILE_VERSION,
    )

    assert dataset.samples == ()
    assert dataset.quality["duplicate_pair"] == 2
    assert dataset.quality["invalid_timestamp"] == 0
    conn.close()
