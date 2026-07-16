"""Run a network-free Opportunity v2.0 Shadow smoke verification."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.db import backend_name, get_connection, init_db, scalar
from app.opportunity.models import EvidenceRecord
from app.opportunity.profile import MODEL_VERSION
from app.opportunity.repository import OpportunityRepository
from app.opportunity.service import OpportunityService
from app.repository import ProjectRepository

PROJECT_ID = "c181bf46-a184-5f97-915d-862c14d8c38f"
LEGACY_SCORE = 87
LEGACY_LABEL = "FARM"


def _evidence(
    factor_key: str,
    value: Any,
    *,
    now: datetime,
    observation_type: str = "observed",
    source_grade: str = "A",
    source_type: str = "official_docs",
    independence_group: str | None = None,
) -> EvidenceRecord:
    value_type = {
        bool: "bool",
        float: "number",
        int: "number",
        str: "string",
        dict: "range",
    }[type(value)]
    return EvidenceRecord(
        project_id=PROJECT_ID,
        factor_key=factor_key,
        value=value,
        value_type=value_type,
        observation_type=observation_type,
        source_url=f"https://example.invalid/opportunity/{factor_key}",
        source_type=source_type,
        source_grade=source_grade,
        observed_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=30),
        verification_status="verified",
        independence_group=independence_group or f"source-{factor_key}",
    )


def _complete_evidence(now: datetime) -> list[EvidenceRecord]:
    official = {"now": now, "independence_group": "official-rules"}
    derived_probability = {
        "now": now,
        "observation_type": "derived",
        "source_grade": "B",
        "source_type": "scoring_model",
        "independence_group": "probability-model",
    }
    derived_economics = {
        "now": now,
        "observation_type": "derived",
        "source_grade": "B",
        "source_type": "cost_model",
        "independence_group": "economics-model",
    }
    verified_risk = {
        "now": now,
        "observation_type": "derived",
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
            **derived_probability,
        ),
        _evidence(
            "eligibility_probability",
            {"low": 0.75, "base": 0.8, "high": 0.9},
            **derived_probability,
        ),
        _evidence(
            "survival_probability",
            {"low": 0.8, "base": 0.9, "high": 0.95},
            **derived_probability,
        ),
        _evidence(
            "conditional_reward_usd",
            {"low": 100, "base": 150, "high": 250},
            **derived_economics,
        ),
        _evidence("hard_cost_usd", {"low": 1, "base": 2, "high": 3}, **derived_economics),
        _evidence(
            "capital_at_risk_usd",
            {"low": 0, "base": 0, "high": 0},
            **derived_economics,
        ),
        _evidence(
            "expected_capital_loss_usd",
            {"low": 0, "base": 0, "high": 0},
            **derived_economics,
        ),
        _evidence(
            "liquidity_cost_usd",
            {"low": 0, "base": 0, "high": 0},
            **derived_economics,
        ),
        _evidence(
            "total_time_hours",
            {"low": 1, "base": 2, "high": 3},
            **derived_economics,
        ),
        _evidence("weekly_maintenance_hours", 1.0, **derived_economics),
        _evidence(
            "project_quality",
            80.0,
            now=now,
            observation_type="derived",
            source_grade="B",
            source_type="quality_model",
            independence_group="quality-model",
        ),
        _evidence("project_failure_risk", "low", **verified_risk),
        _evidence("capital_security_risk", "low", **verified_risk),
        _evidence("eligibility_risk", "low", **verified_risk),
        _evidence("reward_dilution_risk", "low", **verified_risk),
        _evidence("liquidity_risk", "low", **verified_risk),
    ]


def _is_complete(assessment, evidence_count: int) -> bool:
    required = (
        assessment.event_probability,
        assessment.eligibility_probability,
        assessment.survival_probability,
        assessment.reward_probability,
        assessment.conditional_reward_usd,
        assessment.hard_cost_usd,
        assessment.capital_at_risk_usd,
        assessment.expected_capital_loss_usd,
        assessment.liquidity_cost_usd,
        assessment.total_time_hours,
        assessment.weekly_maintenance_hours,
        assessment.economics,
        assessment.project_quality,
        assessment.risks.capital_security,
        assessment.risks.project_failure,
        assessment.risks.eligibility,
        assessment.risks.reward_dilution,
        assessment.risks.liquidity,
        assessment.scored_at,
        assessment.review_at,
        assessment.expires_at,
    )
    return (
        all(value is not None for value in required)
        and assessment.model_version == MODEL_VERSION
        and bool(assessment.factor_snapshot)
        and not assessment.factor_snapshot["critical_unknowns"]
        and len(assessment.evidence_ids) == evidence_count
    )


def run_verification() -> dict[str, bool | int | str]:
    init_db()
    conn = get_connection()
    try:
        conn.execute("DELETE FROM opportunity_assessments WHERE project_id = ?", (PROJECT_ID,))
        conn.execute("DELETE FROM opportunity_evidence WHERE project_id = ?", (PROJECT_ID,))
        conn.execute("DELETE FROM projects WHERE id = ?", (PROJECT_ID,))
        conn.execute(
            """INSERT INTO projects
                   (id, name, sector, stage, score, label, confidence, source)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                PROJECT_ID,
                "Opportunity Shadow Smoke",
                "DeFi",
                "testnet",
                LEGACY_SCORE,
                LEGACY_LABEL,
                0.9,
                "synthetic-smoke",
            ),
        )
        conn.commit()

        project_repo = ProjectRepository(conn)
        opportunity_repo = OpportunityRepository(conn)
        now = datetime.now(UTC)
        service = OpportunityService(
            project_repo=project_repo,
            opportunity_repo=opportunity_repo,
            now_factory=lambda: now,
        )
        sparse = service.evaluate(PROJECT_ID)
        assert sparse.status.value == "INSUFFICIENT_EVIDENCE"
        assert sparse.public_label == "WATCH"

        complete_evidence = _complete_evidence(now)
        for record in complete_evidence:
            opportunity_repo.add_evidence(record)
        complete = service.evaluate(PROJECT_ID)

        assessment_count = scalar(
            conn.execute(
                "SELECT COUNT(*) FROM opportunity_assessments WHERE project_id = ?",
                (PROJECT_ID,),
            ).fetchone()
        )
        legacy = conn.execute("SELECT score, label FROM projects WHERE id = ?", (PROJECT_ID,)).fetchone()
        second_snapshot_complete = _is_complete(complete, len(complete_evidence))
        assert assessment_count == 2
        assert legacy["score"] == LEGACY_SCORE
        assert legacy["label"] == LEGACY_LABEL
        assert second_snapshot_complete

        return {
            "assessment_count": assessment_count,
            "db_backend": backend_name(),
            "legacy_label_unchanged": legacy["label"] == LEGACY_LABEL,
            "legacy_score_unchanged": legacy["score"] == LEGACY_SCORE,
            "model_version": MODEL_VERSION,
            "second_snapshot_complete": second_snapshot_complete,
            "sparse_label": sparse.public_label,
            "sparse_status": sparse.status.value,
        }
    finally:
        conn.close()


def main() -> int:
    try:
        summary = run_verification()
    except Exception as exc:
        print(f"failure_type={type(exc).__name__}")
        print("RESULT: FAIL")
        return 1
    for key in sorted(summary):
        print(f"{key}={summary[key]}")
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
