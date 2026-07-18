"""Run a deterministic, network-free opportunity calibration smoke verification."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import settings  # noqa: F401
from app.db import backend_name, get_connection, init_db
from app.opportunity.calibration import (
    build_calibration_report,
    canonical_report_json,
    load_calibration_dataset,
    render_markdown,
)

MODEL_VERSION = "opportunity-v2.0"
PROFILE_VERSION = "low-cost-curated-multiwallet-v1"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)
PROJECT_IDS = tuple(f"verifier-project-{number}" for number in range(1, 6))
PROJECT_ID_PREFIX = "verifier-project-"
ASSESSMENT_IDS = tuple(f"verifier-assessment-{number}" for number in range(1, 6))
COHORT_IDS = tuple(f"cohort-550e8400-e29b-41d4-a716-44665544{number:04x}" for number in range(1, 6))
PRIVACY_CANARIES = {
    "user_id": "verifier-user-private",
    "activities": "verifier-activities-private",
    "note": "verifier-note-private",
    "disqualification_reason": "verifier-reason-private",
    "recommended_action": "verifier-action-private",
}
MAX_OUTPUT_LINE = 120
EXPECTED_SUMMARY = {
    "backend": "sqlite",
    "json_stable": True,
    "markdown_stable": True,
    "privacy_safe": True,
    "production_select_only": True,
    "window_90d_samples": 3,
    "window_180d_samples": 3,
}
_ASSESSMENT_SELECT = """SELECT assessment_id, project_id, model_version, profile_version,
       assessment_json, scored_at
FROM opportunity_assessments"""
_INTERACTION_SELECT = """SELECT id, project_id, wallet_cohort_id, wallet_count,
       actual_hard_cost_usd, actual_time_minutes, eligibility_result,
       survival_result, reward_received_usd, claim_cost_usd,
       opportunity_assessment_id, opportunity_model_version,
       opportunity_profile_version, outcome_observed_at, outcome
FROM interactions"""
_ALLOWED_PRODUCTION_SELECTS = {_ASSESSMENT_SELECT, _INTERACTION_SELECT}
_EXPECTED_STATEMENTS = (_ASSESSMENT_SELECT, _INTERACTION_SELECT) * 3
_EXPECTED_QUALITY_DELTA = {
    "invalid_project_id": 0,
    "missing_linkage": 0,
    "mismatched_project": 0,
    "unsupported_version": 0,
    "missing_or_invalid_cohort": 0,
    "malformed_assessment_json": 0,
    "invalid_timestamp": 0,
    "duplicate_pair": 2,
}
_FORBIDDEN_REPORT_KEYS = {
    "activities",
    "assessment_id",
    "cohort_id",
    "disqualification_reason",
    "note",
    "project_id",
    "recommended_action",
    "source_url",
    "user_id",
    "wallet_address",
    "wallet_cohort_id",
}


class NonReadOnlyStatementError(RuntimeError):
    """Raised when the production loader attempts anything except its known SELECTs."""


class ArgumentError(ValueError):
    """Sanitized command-line parse failure."""


class _BoundedArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ArgumentError("invalid arguments")


def _print_failure(exception_type: type[BaseException]) -> None:
    prefix = "failure_type="
    available = MAX_OUTPUT_LINE - len(prefix)
    name = exception_type.__name__[:available] or "Exception"
    print(f"{prefix}{name}")
    print("RESULT: FAIL")


def _print_verification_mismatch() -> None:
    print("failure_type=VerificationMismatch")
    print("RESULT: FAIL")


class _RecordingConnection:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.kind = connection.kind
        self.statements: list[str] = []

    def execute(self, sql: str, params: Any = None):
        statement = sql.strip().rstrip(";").strip()
        if not statement or statement not in _ALLOWED_PRODUCTION_SELECTS:
            raise NonReadOnlyStatementError("production loader issued a non-read-only statement")
        self.statements.append(statement)
        return self.connection.execute(sql, params)


def _assessment(assessment_id: str, project_id: str, scored_at: datetime) -> dict[str, Any]:
    probability = {"low": 0.5, "base": 0.7, "high": 0.9}
    return {
        "assessment_id": assessment_id,
        "project_id": project_id,
        "model_version": MODEL_VERSION,
        "profile_version": PROFILE_VERSION,
        "event_probability": probability,
        "eligibility_probability": probability,
        "survival_probability": probability,
        "reward_probability": probability,
        "conditional_reward_usd": {"low": 50, "base": 100, "high": 200},
        "hard_cost_usd": {"low": 2, "base": 5, "high": 10},
        "total_time_hours": {"low": 2, "base": 4, "high": 8},
        "economics": {
            "gross_reward": {"low": 20, "base": 70, "high": 180},
            "net_reward": {"low": 10, "base": 65, "high": 170},
            "reward_to_cost_ratio": 13,
            "decision_value": 65,
            "capital_efficiency": 13,
            "time_efficiency": 16.25,
        },
        "risks": {},
        "confidence": {
            "event": 0.8,
            "eligibility": 0.8,
            "reward": 0.8,
            "cost": 0.8,
            "risk": 0.8,
            "quality": 0.8,
            "overall": 0.8,
        },
        "status": "ACTIONABLE",
        "public_label": "FARM",
        "recommended_action": PRIVACY_CANARIES["recommended_action"],
        "scored_at": scored_at.isoformat(),
        "review_at": (scored_at + timedelta(days=7)).isoformat(),
        "expires_at": (scored_at + timedelta(days=30)).isoformat(),
    }


def _insert_fixture(conn: Any, *, as_of: datetime) -> tuple[tuple[str, ...], tuple[str, ...]]:
    run_id = uuid.uuid4().hex
    assessment_ids = tuple(f"{assessment_id}-{run_id}" for assessment_id in ASSESSMENT_IDS)
    cohort_ids = tuple(f"cohort-{uuid.uuid4()}" for _ in COHORT_IDS)
    for number, (project_id, assessment_id, cohort_id) in enumerate(
        zip(PROJECT_IDS, assessment_ids, cohort_ids, strict=True), 1
    ):
        scored_at = AS_OF - timedelta(days=(200 if number == 1 else 300 if number == 2 else 400 if number == 3 else 30))
        assessment = _assessment(assessment_id, project_id, scored_at)
        observed_at = as_of if number <= 3 else scored_at + timedelta(days=1)
        conn.execute(
            """INSERT INTO opportunity_assessments
               (assessment_id, project_id, model_version, profile_version, assessment_json,
                decision_status, public_label, overall_confidence, scored_at, review_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                assessment_id,
                project_id,
                MODEL_VERSION,
                PROFILE_VERSION,
                json.dumps(assessment, sort_keys=True),
                "ACTIONABLE",
                "FARM",
                0.8,
                scored_at.isoformat(),
                assessment["review_at"],
                assessment["expires_at"],
            ),
        )
        conn.execute(
            """INSERT INTO interactions
               (project_id, user_id, wallet_cohort_id, wallet_count, actual_hard_cost_usd,
                 actual_time_minutes, eligibility_result, survival_result, reward_received_usd,
                 claim_cost_usd, activities, note, disqualification_reason,
                 opportunity_assessment_id, opportunity_model_version,
                 opportunity_profile_version, outcome_observed_at, outcome)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                PRIVACY_CANARIES["user_id"],
                cohort_id,
                number,
                5.0,
                60,
                "eligible",
                "passed",
                75.0,
                1.0,
                PRIVACY_CANARIES["activities"],
                PRIVACY_CANARIES["note"],
                PRIVACY_CANARIES["disqualification_reason"],
                assessment_id,
                MODEL_VERSION,
                PROFILE_VERSION,
                observed_at.isoformat(),
                "airdropped",
            ),
        )
    # Contradictory outcome is retained as a valid linked sample for quality reporting.
    conn.execute(
        "UPDATE interactions SET survival_result = 'disqualified' WHERE opportunity_assessment_id = ?",
        (assessment_ids[2],),
    )
    # Duplicate pair: both rows are rejected by the production loader.
    conn.execute(
        """INSERT INTO interactions
           (project_id, wallet_cohort_id, wallet_count, opportunity_assessment_id,
            opportunity_model_version, opportunity_profile_version, outcome_observed_at, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            PROJECT_IDS[4],
            cohort_ids[4],
            2,
            assessment_ids[4],
            MODEL_VERSION,
            PROFILE_VERSION,
            AS_OF.isoformat(),
            "duplicate",
        ),
    )
    return assessment_ids, cohort_ids


def _report_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value).union(*(map(_report_keys, value.values())), set())
    if isinstance(value, (tuple, list)):
        return set().union(*(map(_report_keys, value)), set())
    return set()


def _assert_report_contract(
    dataset: Any,
    report: dict[str, Any],
    *,
    baseline_quality: dict[str, int],
    as_of: datetime,
) -> None:
    assert set(dataset.quality) == set(_EXPECTED_QUALITY_DELTA)
    assert {
        key: int(dataset.quality[key]) - baseline_quality[key] for key in _EXPECTED_QUALITY_DELTA
    } == _EXPECTED_QUALITY_DELTA
    assert report["metadata"] == {
        "schema": "opportunity-calibration-v1",
        "model_version": MODEL_VERSION,
        "profile_version": PROFILE_VERSION,
        "as_of": as_of.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "windows": [90, 180],
        "bootstrap_seed": 20260717,
        "bootstrap_replicates": 1000,
        "database_backend": backend_name(),
        "report_id": report["metadata"]["report_id"],
    }
    assert report["data_quality"] == {
        "linked_sample_count": 4,
        "loader": {key: int(dataset.quality[key]) for key in _EXPECTED_QUALITY_DELTA},
        "maturity": {
            "90d": {"mature": 3, "immature": 1, "outcome_before_assessment": 0, "outcome_after_as_of": 0},
            "180d": {"mature": 3, "immature": 1, "outcome_before_assessment": 0, "outcome_after_as_of": 0},
        },
    }
    assert set(report) == {"metadata", "data_quality", "windows"}
    assert set(report["windows"]) == {"90d", "180d"}
    assert not (_report_keys(report) & _FORBIDDEN_REPORT_KEYS)
    for window_name in ("90d", "180d"):
        window = report["windows"][window_name]
        assert window["quality"]["contradictory_outcomes"] == 1
        assert window["gate"] == "data_quality_only"
        economics = window["project_equal"]["economic"]
        assert economics["net_reward"]["sample_count"] == 2
        assert economics["net_reward"]["mean_signed_error"] == 4.0
        assert economics["hard_cost"]["mean_signed_error"] == 0.0
        assert economics["total_time"]["mean_signed_error"] == -3.0
        decision = window["project_equal"]["decision"]
        assert decision["sample_count"] == 2
        assert decision["project_count"] == 2
        assert decision["confusion_matrix"]["FARM"]["POSITIVE"] == 2.0
        assert decision["gate"] == "data_quality_only"


def run_verification(
    as_of: datetime = AS_OF,
    *,
    loader: Callable[..., Any] = load_calibration_dataset,
) -> dict[str, Any]:
    """Load fixed fixture rows through production SELECT-only APIs and verify reports."""
    init_db()
    conn = get_connection()
    try:
        conn.begin_serialized_write()
        recorded = _RecordingConnection(conn)
        baseline = loader(recorded, model_version=MODEL_VERSION, profile_version=PROFILE_VERSION)
        baseline_quality = {key: int(baseline.quality[key]) for key in _EXPECTED_QUALITY_DELTA}
        assessment_ids, cohort_ids = _insert_fixture(conn, as_of=as_of)
        dataset = loader(recorded, model_version=MODEL_VERSION, profile_version=PROFILE_VERSION)
        report = build_calibration_report(dataset, as_of=as_of)
        dataset_again = loader(recorded, model_version=MODEL_VERSION, profile_version=PROFILE_VERSION)
        report_again = build_calibration_report(dataset_again, as_of=as_of)
        json_bytes = canonical_report_json(report)
        markdown = render_markdown(report)
        _assert_report_contract(dataset, report, baseline_quality=baseline_quality, as_of=as_of)
        _assert_report_contract(dataset_again, report_again, baseline_quality=baseline_quality, as_of=as_of)
        private_values = PROJECT_IDS + assessment_ids + cohort_ids + tuple(PRIVACY_CANARIES.values())
        return {
            "backend": backend_name(),
            "json_stable": json_bytes == canonical_report_json(report_again),
            "markdown_stable": markdown == render_markdown(report_again),
            "privacy_safe": not any(token.encode() in json_bytes or token in markdown for token in private_values),
            "production_select_only": tuple(recorded.statements) == _EXPECTED_STATEMENTS,
            "window_90d_samples": report["windows"]["90d"]["mature_sample_count"],
            "window_180d_samples": report["windows"]["180d"]["mature_sample_count"],
        }
    finally:
        try:
            conn.rollback()
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = _BoundedArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of", type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")), default=AS_OF
    )
    try:
        summary = run_verification(parser.parse_args(argv).as_of)
    except Exception as exc:  # intentionally bounded to avoid leaking fixture/config details
        _print_failure(type(exc))
        return 1
    lines = [f"{key}={summary[key]}" for key in sorted(summary)]
    expected = dict(EXPECTED_SUMMARY, backend=summary.get("backend"))
    passed = summary.get("backend") in {"sqlite", "postgres"} and summary == expected
    if not passed:
        _print_verification_mismatch()
        return 1
    lines.append(f"RESULT: {'PASS' if passed else 'FAIL'}")
    if any(len(line) > MAX_OUTPUT_LINE for line in lines):
        print("failure_type=OutputLineTooLong")
        print("RESULT: FAIL")
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
