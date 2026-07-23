"""Append-only repository for opportunity economic snapshots.

Task 2: dual-backend get / insert-if-absent only. No UPDATE, no network,
no Evidence emit, no identity resolution.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Collection
from typing import Any

from app.db import _as_db_connection
from app.opportunity.economic_models import EconomicSnapshotRow, canonical_json_bytes

_SNAPSHOT_COLUMNS = (
    "snapshot_id",
    "schema_version",
    "run_id",
    "source_id",
    "dedup_key",
    "provider_entity_id",
    "payload_sha256",
    "payload_json",
    "source_url",
    "collected_at",
)

# Fixed column list only (mirrors _SNAPSHOT_COLUMNS); no user input in SQL text.
_SELECT_BY_ID = (
    "SELECT snapshot_id, schema_version, run_id, source_id, dedup_key, "
    "provider_entity_id, payload_sha256, payload_json, source_url, collected_at "
    "FROM opportunity_economic_snapshots WHERE snapshot_id = ?"
)

_INSERT = (
    "INSERT INTO opportunity_economic_snapshots ("
    "snapshot_id, schema_version, run_id, source_id, dedup_key, "
    "provider_entity_id, payload_sha256, payload_json, source_url, collected_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
)


class EconomicSnapshotContentConflict(RuntimeError):  # noqa: N818 — frozen public API name
    """Raised when snapshot_id exists with non-equivalent frozen content."""


def _is_integrity_error(exc: BaseException) -> bool:
    """True for unique/PK collisions only (not check/FK violations).

    Prefer psycopg3 ``sqlstate``; retain ``pgcode`` and documented class-name
    fallbacks for compatible drivers/wrappers.
    """
    if isinstance(exc, sqlite3.IntegrityError):
        return True
    # psycopg3 UniqueViolation exposes sqlstate; older adapters used pgcode.
    for attr in ("sqlstate", "pgcode"):
        if getattr(exc, attr, None) == "23505":
            return True
    name = type(exc).__name__
    return name in {"IntegrityError", "UniqueViolation"}


def _payload_text(payload_json: Any) -> str:
    return canonical_json_bytes(payload_json).decode("utf-8")


def _ten_fields_equal(existing: EconomicSnapshotRow, incoming: EconomicSnapshotRow) -> bool:
    """Duplicate equivalence for insert-if-absent (no UPDATE semantics).

    Compares every frozen contract field except ``collected_at``. Timestamp drift
    alone is retry metadata: return the existing immutable row unchanged. Any
    other field difference remains a content conflict. Canonical ``payload_json``
    equivalence is unchanged.
    """
    return (
        existing.snapshot_id == incoming.snapshot_id
        and existing.schema_version == incoming.schema_version
        and existing.run_id == incoming.run_id
        and existing.source_id == incoming.source_id
        and existing.dedup_key == incoming.dedup_key
        and existing.provider_entity_id == incoming.provider_entity_id
        and existing.payload_sha256 == incoming.payload_sha256
        and existing.source_url == incoming.source_url
        and canonical_json_bytes(existing.payload_json)
        == canonical_json_bytes(incoming.payload_json)
    )


def _row_to_snapshot(row: Any) -> EconomicSnapshotRow:
    payload_raw = row["payload_json"]
    if isinstance(payload_raw, (bytes, bytearray)):
        payload_raw = payload_raw.decode("utf-8")
    payload = json.loads(payload_raw) if isinstance(payload_raw, str) else payload_raw
    return EconomicSnapshotRow(
        snapshot_id=row["snapshot_id"],
        schema_version=row["schema_version"],
        run_id=row["run_id"],
        source_id=row["source_id"],
        dedup_key=row["dedup_key"],
        provider_entity_id=row["provider_entity_id"],
        payload_sha256=row["payload_sha256"],
        payload_json=payload,
        source_url=row["source_url"],
        collected_at=row["collected_at"],
    )


class EconomicSnapshotRepository:
    def __init__(self, conn: Any = None) -> None:
        self._db, self._owns_connection = _as_db_connection(conn)

    def close(self) -> None:
        if self._owns_connection:
            self._db.close()

    def __enter__(self) -> EconomicSnapshotRepository:
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def get(self, snapshot_id: str) -> EconomicSnapshotRow | None:
        row = self._db.execute(_SELECT_BY_ID, (snapshot_id,)).fetchone()
        if row is None:
            return None
        return _row_to_snapshot(row)

    def source_ids_by_snapshot_id(self, snapshot_ids: Collection[str]) -> dict[str, str]:
        """Batch-read snapshot_id → source_id. Empty input: no query."""
        ids = list(snapshot_ids)
        if not ids:
            return {}
        # Placeholders are only "?" markers; ids bind via parameters (no user SQL).
        placeholders = ", ".join("?" for _ in ids)
        sql = (
            "SELECT snapshot_id, source_id FROM opportunity_economic_snapshots WHERE "  # noqa: S608
            f"snapshot_id IN ({placeholders})"
        )
        rows = self._db.execute(sql, tuple(ids)).fetchall()
        return {row["snapshot_id"]: row["source_id"] for row in rows}

    def find_linked_project_id(self, source_id: str, dedup_key: str) -> str | None:
        """Return project_id only when exact raw identity is linked and projects.id exists.

        Conditions (all required; no symbol/name/slug/fuzzy):
        1. ``raw_projects`` row matches exact ``(source_id, dedup_key)``
        2. that row's ``project_id`` is non-empty
        3. ``projects.id`` exists for that ``project_id``
        """
        row = self._db.execute(
            """
            SELECT rp.project_id AS project_id
            FROM raw_projects rp
            INNER JOIN projects p ON p.id = rp.project_id
            WHERE rp.source_id = ?
              AND rp.dedup_key = ?
              AND rp.project_id IS NOT NULL
              AND TRIM(rp.project_id) != ''
            LIMIT 1
            """,
            (source_id, dedup_key),
        ).fetchone()
        if row is None:
            return None
        project_id = row["project_id"]
        if project_id is None:
            return None
        text = str(project_id).strip()
        return text if text else None

    def list_by_identity(
        self, source_id: str, dedup_key: str
    ) -> tuple[EconomicSnapshotRow, ...]:
        """Return all snapshots for exact ``(source_id, dedup_key)`` identity only."""
        rows = self._db.execute(
            "SELECT snapshot_id, schema_version, run_id, source_id, dedup_key, "
            "provider_entity_id, payload_sha256, payload_json, source_url, collected_at "
            "FROM opportunity_economic_snapshots "
            "WHERE source_id = ? AND dedup_key = ? "
            "ORDER BY collected_at ASC, snapshot_id ASC",
            (source_id, dedup_key),
        ).fetchall()
        return tuple(_row_to_snapshot(row) for row in rows)

    def insert_if_absent(self, snapshot: EconomicSnapshotRow) -> tuple[EconomicSnapshotRow, bool]:
        params = (
            snapshot.snapshot_id,
            snapshot.schema_version,
            snapshot.run_id,
            snapshot.source_id,
            snapshot.dedup_key,
            snapshot.provider_entity_id,
            snapshot.payload_sha256,
            _payload_text(snapshot.payload_json),
            snapshot.source_url,
            snapshot.collected_at,
        )
        try:
            self._db.execute(_INSERT, params)
            self._db.commit()
        except Exception as exc:
            self._db.rollback()
            if not _is_integrity_error(exc):
                raise
            existing = self.get(snapshot.snapshot_id)
            if existing is None:
                raise
            if _ten_fields_equal(existing, snapshot):
                return existing, False
            raise EconomicSnapshotContentConflict(
                f"opportunity_economic_snapshots content conflict for "
                f"snapshot_id={snapshot.snapshot_id!r}"
            ) from exc
        return snapshot, True
