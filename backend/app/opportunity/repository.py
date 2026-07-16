import json
import uuid
from datetime import UTC, datetime
from types import TracebackType
from typing import Any

from app.db import _as_db_connection
from app.opportunity.models import (
    EvidenceRecord,
    OpportunityAssessment,
    validate_source_url,
)


def _as_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


class OpportunityRepository:
    def __init__(self, conn: Any = None):
        self._conn, self._owns_connection = _as_db_connection(conn)

    def add_evidence(self, record: EvidenceRecord) -> EvidenceRecord:
        validate_source_url(record.source_url)
        stored = record.model_copy(update={"evidence_id": record.evidence_id or str(uuid.uuid4())})
        serialized = stored.model_dump(mode="json")
        try:
            if stored.supersedes_evidence_id is not None:
                target = self._conn.execute(
                    """SELECT project_id, factor_key, observed_at FROM opportunity_evidence
                       WHERE evidence_id = ?""",
                    (stored.supersedes_evidence_id,),
                ).fetchone()
                if target is None:
                    raise ValueError("supersession target must be existing evidence")
                if target["project_id"] != stored.project_id or target["factor_key"] != stored.factor_key:
                    raise ValueError("supersession target must have the same project and factor")
                if _as_utc(target["observed_at"]) > _as_utc(stored.observed_at):
                    raise ValueError("supersession target must be chronological")
                current_id = stored.supersedes_evidence_id
                visited: set[str] = set()
                while current_id is not None:
                    if current_id == stored.evidence_id or current_id in visited:
                        raise ValueError("supersession must not create a cycle")
                    visited.add(current_id)
                    ancestor = self._conn.execute(
                        """SELECT supersedes_evidence_id FROM opportunity_evidence
                           WHERE evidence_id = ?""",
                        (current_id,),
                    ).fetchone()
                    current_id = ancestor["supersedes_evidence_id"] if ancestor is not None else None
            self._conn.execute(
                """INSERT INTO opportunity_evidence (
                       evidence_id, project_id, factor_key, value_json, value_type,
                       observation_type, source_url, source_type, source_grade,
                       observed_at, effective_at, expires_at, verification_status,
                       independence_group, raw_snapshot_ref, supersedes_evidence_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    stored.evidence_id,
                    stored.project_id,
                    stored.factor_key,
                    json.dumps(serialized["value"], ensure_ascii=False),
                    stored.value_type,
                    stored.observation_type,
                    str(stored.source_url),
                    stored.source_type,
                    stored.source_grade,
                    serialized["observed_at"],
                    serialized["effective_at"],
                    serialized["expires_at"],
                    stored.verification_status,
                    stored.independence_group,
                    stored.raw_snapshot_ref,
                    stored.supersedes_evidence_id,
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return stored

    def list_evidence(self, project_id: str, include_invalid: bool = False) -> list[EvidenceRecord]:
        sql = """SELECT evidence_id, project_id, factor_key, value_json, value_type,
                        observation_type, source_url, source_type, source_grade,
                        observed_at, effective_at, expires_at, verification_status,
                        independence_group, raw_snapshot_ref, supersedes_evidence_id
                 FROM opportunity_evidence
                 WHERE project_id = ?"""
        params: tuple[Any, ...] = (project_id,)
        if not include_invalid:
            sql += " AND verification_status != ?"
            params += ("invalidated",)
        sql += " ORDER BY observed_at DESC, created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            EvidenceRecord(
                evidence_id=row["evidence_id"],
                project_id=row["project_id"],
                factor_key=row["factor_key"],
                value=json.loads(row["value_json"]),
                value_type=row["value_type"],
                observation_type=row["observation_type"],
                source_url=row["source_url"],
                source_type=row["source_type"],
                source_grade=row["source_grade"],
                observed_at=row["observed_at"],
                effective_at=row["effective_at"],
                expires_at=row["expires_at"],
                verification_status=row["verification_status"],
                independence_group=row["independence_group"],
                raw_snapshot_ref=row["raw_snapshot_ref"],
                supersedes_evidence_id=row["supersedes_evidence_id"],
            )
            for row in rows
        ]

    def save_assessment(self, assessment: OpportunityAssessment) -> OpportunityAssessment:
        assessment_id = assessment.assessment_id or str(uuid.uuid4())
        payload = assessment.model_copy(update={"assessment_id": assessment_id})
        serialized = payload.model_dump(mode="json")
        try:
            self._conn.execute(
                """INSERT INTO opportunity_assessments (
                       assessment_id, project_id, model_version, profile_version,
                       assessment_json, decision_status, public_label, decision_value,
                       overall_confidence, scored_at, review_at, expires_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    payload.project_id,
                    payload.model_version,
                    payload.profile_version,
                    payload.model_dump_json(),
                    payload.status.value,
                    payload.public_label,
                    payload.economics.decision_value if payload.economics else None,
                    payload.confidence.overall,
                    serialized["scored_at"],
                    serialized["review_at"],
                    serialized["expires_at"],
                ),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return payload

    def latest_assessment(self, project_id: str, profile_id: str) -> OpportunityAssessment | None:
        row = self._conn.execute(
            """SELECT assessment_json
               FROM opportunity_assessments
               WHERE project_id = ? AND profile_version = ?
               ORDER BY scored_at DESC, created_at DESC, assessment_id DESC
               LIMIT 1""",
            (project_id, profile_id),
        ).fetchone()
        if row is None:
            return None
        return OpportunityAssessment.model_validate_json(row["assessment_json"])

    def close(self) -> None:
        if self._owns_connection:
            self._conn.close()

    def __enter__(self) -> "OpportunityRepository":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()
