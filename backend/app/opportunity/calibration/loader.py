from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.opportunity.models import OpportunityAssessment

from .models import CalibrationDataset, CalibrationSample, RangeValue

_ASSESSMENT_SQL = """
SELECT assessment_id, project_id, model_version, profile_version,
       assessment_json, scored_at
FROM opportunity_assessments
"""

_INTERACTION_SQL = """
SELECT id, project_id, wallet_cohort_id, wallet_count,
       actual_hard_cost_usd, actual_time_minutes, eligibility_result,
       survival_result, reward_received_usd, claim_cost_usd,
       opportunity_assessment_id, opportunity_model_version,
       opportunity_profile_version, outcome_observed_at, outcome
FROM interactions
"""

_QUALITY_KEYS = (
    "missing_linkage",
    "mismatched_project",
    "unsupported_version",
    "missing_or_invalid_cohort",
    "malformed_assessment_json",
    "invalid_timestamp",
    "duplicate_pair",
)


def _rows(cursor: Any) -> list[dict[str, Any]]:
    names = [column[0] for column in cursor.description]
    return [dict(row) if hasattr(row, "keys") else dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _range(value: Any) -> RangeValue:
    return RangeValue(value.low, value.base, value.high)


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty string or datetime")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


def _valid_cohort_id(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith("cohort-"):
        return False
    supplied_uuid = value.removeprefix("cohort-")
    try:
        parsed = uuid.UUID(supplied_uuid)
    except (AttributeError, ValueError):
        return False
    return (
        supplied_uuid.lower() == str(parsed)
        and parsed.int != 0
        and parsed.version == 4
        and parsed.variant == uuid.RFC_4122
    )


def _assessment_from_row(row: dict[str, Any]) -> OpportunityAssessment | None:
    try:
        assessment = OpportunityAssessment.model_validate_json(row["assessment_json"])
    except (TypeError, ValidationError, ValueError):
        return None

    required_ranges = (
        assessment.event_probability,
        assessment.eligibility_probability,
        assessment.survival_probability,
        assessment.reward_probability,
        assessment.economics.net_reward if assessment.economics else None,
        assessment.hard_cost_usd,
        assessment.total_time_hours,
    )
    if any(value is None for value in required_ranges):
        return None
    return assessment


def _build_sample(
    assessment_row: dict[str, Any],
    assessment: OpportunityAssessment,
    interaction: dict[str, Any],
    *,
    scored_at: datetime,
    observed_at: datetime,
) -> CalibrationSample:
    return CalibrationSample(
        project_id=assessment_row["project_id"],
        assessment_id=assessment_row["assessment_id"],
        cohort_id=interaction["wallet_cohort_id"].strip(),
        scored_at=scored_at,
        outcome_observed_at=observed_at,
        model_version=assessment_row["model_version"],
        profile_version=assessment_row["profile_version"],
        status=str(assessment.status),
        public_label=assessment.public_label,
        wallet_count=interaction["wallet_count"],
        event_probability=_range(assessment.event_probability),
        eligibility_probability=_range(assessment.eligibility_probability),
        survival_probability=_range(assessment.survival_probability),
        reward_probability=_range(assessment.reward_probability),
        net_reward=_range(assessment.economics.net_reward),
        hard_cost=_range(assessment.hard_cost_usd),
        total_time_hours=_range(assessment.total_time_hours),
        outcome=interaction["outcome"],
        eligibility_result=interaction["eligibility_result"],
        survival_result=interaction["survival_result"],
        reward_received_usd=interaction["reward_received_usd"],
        actual_hard_cost_usd=interaction["actual_hard_cost_usd"],
        claim_cost_usd=interaction["claim_cost_usd"],
        actual_time_minutes=interaction["actual_time_minutes"],
    )


def load_calibration_dataset(
    conn: Any,
    *,
    model_version: str,
    profile_version: str,
) -> CalibrationDataset:
    assessment_rows = _rows(conn.execute(_ASSESSMENT_SQL))
    interaction_rows = _rows(conn.execute(_INTERACTION_SQL))
    assessment_rows_by_id = {row["assessment_id"]: row for row in assessment_rows}
    quality = dict.fromkeys(_QUALITY_KEYS, 0)
    candidates: list[CalibrationSample] = []
    pair_counts = Counter(
        (
            interaction["opportunity_assessment_id"],
            interaction["wallet_cohort_id"],
        )
        for interaction in interaction_rows
    )

    for interaction in interaction_rows:
        pair = (
            interaction["opportunity_assessment_id"],
            interaction["wallet_cohort_id"],
        )
        if pair_counts[pair] > 1:
            quality["duplicate_pair"] += 1
            continue

        assessment_row = assessment_rows_by_id.get(interaction["opportunity_assessment_id"])
        if assessment_row is None:
            quality["missing_linkage"] += 1
            continue

        if interaction["project_id"] != assessment_row["project_id"]:
            quality["mismatched_project"] += 1
            continue

        versions = (
            assessment_row["model_version"],
            assessment_row["profile_version"],
            interaction["opportunity_model_version"],
            interaction["opportunity_profile_version"],
        )
        if versions != (model_version, profile_version, model_version, profile_version):
            quality["unsupported_version"] += 1
            continue

        cohort_id = interaction["wallet_cohort_id"]
        wallet_count = interaction["wallet_count"]
        if (
            not _valid_cohort_id(cohort_id)
            or not isinstance(wallet_count, int)
            or isinstance(wallet_count, bool)
            or wallet_count <= 0
        ):
            quality["missing_or_invalid_cohort"] += 1
            continue

        assessment = _assessment_from_row(assessment_row)
        if assessment is None:
            quality["malformed_assessment_json"] += 1
            continue
        if assessment.project_id != assessment_row["project_id"]:
            quality["mismatched_project"] += 1
            continue
        if (
            assessment.model_version != model_version
            or assessment.profile_version != profile_version
            or assessment.assessment_id != assessment_row["assessment_id"]
        ):
            quality["unsupported_version"] += 1
            continue

        try:
            scored_at = _timestamp(assessment_row["scored_at"])
            observed_at = _timestamp(interaction["outcome_observed_at"])
        except (TypeError, ValueError):
            quality["invalid_timestamp"] += 1
            continue

        candidates.append(
            _build_sample(
                assessment_row,
                assessment,
                interaction,
                scored_at=scored_at,
                observed_at=observed_at,
            )
        )

    candidates.sort(key=lambda sample: (sample.project_id, sample.assessment_id, sample.cohort_id))

    return CalibrationDataset(
        samples=tuple(candidates),
        quality=quality,
        backend=getattr(conn, "kind", "sqlite"),
    )
