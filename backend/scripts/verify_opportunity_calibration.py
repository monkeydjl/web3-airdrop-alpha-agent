"""Run a deterministic, network-free opportunity calibration smoke verification."""

from __future__ import annotations

import argparse
import json
import sys
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
ASSESSMENT_IDS = tuple(f"verifier-assessment-{number}" for number in range(1, 6))
COHORT_IDS = tuple(f"cohort-550e8400-e29b-41d4-a716-44665544{number:04x}" for number in range(1, 6))
PRIVACY_TOKENS = ("verifier-user-private", "verifier-note-private", "verifier-reason-private")
MAX_OUTPUT_LINE = 120


class _RecordingConnection:
    def __init__(self, connection: Any) -> None:
        self.connection = connection
        self.kind = connection.kind
        self.statements: list[str] = []

    def execute(self, sql: str, params: Any = None):
        self.statements.append(sql)
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
        "confidence": {"event": 0.8, "eligibility": 0.8, "reward": 0.8, "cost": 0.8, "risk": 0.8, "quality": 0.8, "overall": 0.8},
        "status": "ACTIONABLE",
        "public_label": "FARM",
        "recommended_action": "Proceed.",
        "scored_at": scored_at.isoformat(),
        "review_at": (scored_at + timedelta(days=7)).isoformat(),
        "expires_at": (scored_at + timedelta(days=30)).isoformat(),
    }


def _insert_fixture(conn: Any, *, as_of: datetime) -> None:
    for number, (project_id, assessment_id, cohort_id) in enumerate(zip(PROJECT_IDS, ASSESSMENT_IDS, COHORT_IDS, strict=True), 1):
        scored_at = AS_OF - timedelta(days=(200 if number == 1 else 300 if number == 2 else 400 if number == 3 else 30))
        assessment = _assessment(assessment_id, project_id, scored_at)
        observed_at = as_of if number <= 3 else scored_at + timedelta(days=1)
        conn.execute(
            """INSERT INTO opportunity_assessments
               (assessment_id, project_id, model_version, profile_version, assessment_json,
                decision_status, public_label, overall_confidence, scored_at, review_at, expires_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (assessment_id, project_id, MODEL_VERSION, PROFILE_VERSION, json.dumps(assessment, sort_keys=True), "ACTIONABLE", "FARM", 0.8, scored_at.isoformat(), assessment["review_at"], assessment["expires_at"]),
        )
        conn.execute(
            """INSERT INTO interactions
               (project_id, user_id, wallet_cohort_id, wallet_count, actual_hard_cost_usd,
                actual_time_minutes, eligibility_result, survival_result, reward_received_usd,
                claim_cost_usd, note, disqualification_reason,
                opportunity_assessment_id, opportunity_model_version,
                opportunity_profile_version, outcome_observed_at, outcome)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                project_id,
                PRIVACY_TOKENS[0],
                cohort_id,
                number,
                5.0,
                60,
                "eligible",
                "passed",
                75.0,
                1.0,
                PRIVACY_TOKENS[1],
                PRIVACY_TOKENS[2],
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
        (ASSESSMENT_IDS[2],),
    )
    # Duplicate pair: both rows are rejected by the production loader.
    conn.execute(
        """INSERT INTO interactions
           (project_id, wallet_cohort_id, wallet_count, opportunity_assessment_id,
            opportunity_model_version, opportunity_profile_version, outcome_observed_at, outcome)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (PROJECT_IDS[4], COHORT_IDS[4], 2, ASSESSMENT_IDS[4], MODEL_VERSION, PROFILE_VERSION, AS_OF.isoformat(), "duplicate"),
    )
    conn.commit()


def run_verification(as_of: datetime = AS_OF) -> dict[str, Any]:
    """Load fixed fixture rows through production SELECT-only APIs and verify reports."""
    init_db()
    conn = get_connection()
    try:
        placeholders = ", ".join("?" for _ in PROJECT_IDS)
        conn.execute(f"DELETE FROM interactions WHERE project_id IN ({placeholders})", PROJECT_IDS)  # noqa: S608
        conn.execute(f"DELETE FROM opportunity_assessments WHERE project_id IN ({placeholders})", PROJECT_IDS)  # noqa: S608
        _insert_fixture(conn, as_of=as_of)
        recorded = _RecordingConnection(conn)
        dataset = load_calibration_dataset(recorded, model_version=MODEL_VERSION, profile_version=PROFILE_VERSION)
        report = build_calibration_report(dataset, as_of=as_of)
        report_again = build_calibration_report(dataset, as_of=as_of)
        json_bytes = canonical_report_json(report)
        markdown = render_markdown(report)
        assert dataset.quality["duplicate_pair"] == 2
        assert report["data_quality"]["maturity"]["90d"]["immature"] == 1
        assert report["data_quality"]["maturity"]["180d"]["immature"] == 1
        assert report["windows"]["90d"]["quality"]["contradictory_outcomes"] == 1
        assert report["windows"]["180d"]["quality"]["contradictory_outcomes"] == 1
        assert report["metadata"]["database_backend"] == backend_name()
        private_values = PROJECT_IDS + ASSESSMENT_IDS + COHORT_IDS + PRIVACY_TOKENS
        return {
            "backend": backend_name(),
            "json_stable": json_bytes == canonical_report_json(report_again),
            "markdown_stable": markdown == render_markdown(report_again),
            "privacy_safe": not any(token.encode() in json_bytes or token in markdown for token in private_values),
            "production_select_only": all(statement.lstrip().upper().startswith("SELECT") for statement in recorded.statements),
            "window_90d_samples": report["windows"]["90d"]["mature_sample_count"],
            "window_180d_samples": report["windows"]["180d"]["mature_sample_count"],
        }
    finally:
        try:
            placeholders = ", ".join("?" for _ in PROJECT_IDS)
            conn.execute(f"DELETE FROM interactions WHERE project_id IN ({placeholders})", PROJECT_IDS)  # noqa: S608
            conn.execute(f"DELETE FROM opportunity_assessments WHERE project_id IN ({placeholders})", PROJECT_IDS)  # noqa: S608
            conn.commit()
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")), default=AS_OF)
    try:
        summary = run_verification(parser.parse_args(argv).as_of)
    except Exception as exc:  # intentionally bounded to avoid leaking fixture/config details
        print(f"failure_type={type(exc).__name__}")
        print("RESULT: FAIL")
        return 1
    for key in sorted(summary):
        print(f"{key}={summary[key]}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
