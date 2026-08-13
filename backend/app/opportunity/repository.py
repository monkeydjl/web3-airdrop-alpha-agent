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

_EVIDENCE_SELECT_16 = """SELECT evidence_id, project_id, factor_key, value_json, value_type,
                        observation_type, source_url, source_type, source_grade,
                        observed_at, effective_at, expires_at, verification_status,
                        independence_group, raw_snapshot_ref, supersedes_evidence_id
                 FROM opportunity_evidence"""


class EconomicEvidenceContentConflict(RuntimeError):  # noqa: N818 — frozen public API name
    """Raised when evidence_id exists with non-equivalent frozen content."""


def _as_utc(value: datetime | str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00")) if isinstance(value, str) else value
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _row_to_evidence(row: Any) -> EvidenceRecord:
    value_raw = row["value_json"]
    if isinstance(value_raw, (bytes, bytearray)):
        value_raw = value_raw.decode("utf-8")
    value = json.loads(value_raw) if isinstance(value_raw, str) else value_raw
    return EvidenceRecord(
        evidence_id=row["evidence_id"],
        project_id=row["project_id"],
        factor_key=row["factor_key"],
        value=value,
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


def _evidence_insert_params(stored: EvidenceRecord, serialized: dict[str, Any]) -> tuple[Any, ...]:
    return (
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
    )


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
                _evidence_insert_params(stored, serialized),
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        return stored

    def add_economic_evidence_if_absent(self, evidence: EvidenceRecord) -> tuple[EvidenceRecord, bool]:
        """Append-only insert-if-absent for economic Evidence. Never overwrites.

        Returns ``(record, True)`` only on new insert. Equivalent existing row
        (same ``evidence_id`` and ``model_dump(mode="json")``) returns
        ``(existing, False)``. Same id with non-equivalent content raises
        ``EconomicEvidenceContentConflict`` after rollback of the write attempt.
        """
        validate_source_url(evidence.source_url)
        if not evidence.evidence_id:
            raise ValueError("economic evidence requires evidence_id")
        stored = evidence
        serialized = stored.model_dump(mode="json")
        try:
            # RETURNING is the authoritative insert-vs-conflict signal when drivers
            # leave rowcount as None / -1. Preserve exact 0/1 rowcount classification.
            cursor = self._conn.execute(
                """INSERT INTO opportunity_evidence (
                       evidence_id, project_id, factor_key, value_json, value_type,
                       observation_type, source_url, source_type, source_grade,
                       observed_at, effective_at, expires_at, verification_status,
                       independence_group, raw_snapshot_ref, supersedes_evidence_id
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(evidence_id) DO NOTHING
                   RETURNING evidence_id""",
                _evidence_insert_params(stored, serialized),
            )
            rowcount = getattr(cursor, "rowcount", None)
            returned = cursor.fetchone()
            # Prefer RETURNING as insert proof; keep exact rowcount==1 success path.
            # Never treat post-SELECT equality alone as insert under ambiguous rowcount.
            if returned is not None or rowcount == 1:
                self._conn.commit()
                return stored, True
            # Conflict path (rowcount==0 or empty RETURNING): load existing; never UPDATE.
            # Do not commit before content comparison so rollback remains effective.
            existing_row = self._conn.execute(
                _EVIDENCE_SELECT_16 + " WHERE evidence_id = ?",
                (stored.evidence_id,),
            ).fetchone()
            if existing_row is None:
                self._conn.rollback()
                raise RuntimeError(
                    f"economic evidence ON CONFLICT DO NOTHING with missing row for evidence_id={stored.evidence_id!r}"
                )
            existing = _row_to_evidence(existing_row)
            if existing.model_dump(mode="json") == stored.model_dump(mode="json"):
                self._conn.commit()
                return existing, False
            self._conn.rollback()
            raise EconomicEvidenceContentConflict(
                f"opportunity_evidence content conflict for evidence_id={stored.evidence_id!r}"
            )
        except EconomicEvidenceContentConflict:
            raise
        except Exception:
            self._conn.rollback()
            raise

    def list_evidence(self, project_id: str, include_invalid: bool = False) -> list[EvidenceRecord]:
        sql = _EVIDENCE_SELECT_16 + " WHERE project_id = ?"
        params: tuple[Any, ...] = (project_id,)
        if not include_invalid:
            sql += " AND verification_status != ?"
            params += ("invalidated",)
        sql += " ORDER BY observed_at DESC, created_at DESC"
        rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_evidence(row) for row in rows]

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
