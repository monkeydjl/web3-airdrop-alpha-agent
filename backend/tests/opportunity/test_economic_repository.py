"""Task 2: EconomicSnapshotRepository insert-if-absent + dual-backend DDL parity."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from app.db import DbConnection, init_db
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicSnapshotRow,
    build_snapshot_id,
    payload_sha256,
)


def _make_snapshot(
    *,
    run_id: str = "daily:2026-07-22:defillama",
    source_id: str = "defillama",
    dedup_key: str = "protocol:example",
    provider_entity_id: str = "raw-example-1",
    payload: dict[str, Any] | None = None,
    source_url: str = "https://api.llama.fi/protocol/example",
    collected_at: datetime | None = None,
) -> EconomicSnapshotRow:
    body = payload if payload is not None else {"tvl": 1_000_000, "change_7d": 0.05, "change_7d_unit": "ratio"}
    digest = payload_sha256(body)
    snapshot_id = build_snapshot_id(
        run_id=run_id,
        source_id=source_id,
        provider_entity_id=provider_entity_id,
        payload_sha256_hex=digest,
    )
    return EconomicSnapshotRow(
        snapshot_id=snapshot_id,
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        source_id=source_id,
        dedup_key=dedup_key,
        provider_entity_id=provider_entity_id,
        payload_sha256=digest,
        payload_json=body,
        source_url=source_url,
        collected_at=collected_at or datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )


def _sqlite_repo():
    from app.opportunity.economic_repository import EconomicSnapshotRepository

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return raw, conn, EconomicSnapshotRepository(conn)


def test_get_returns_none_for_missing_snapshot() -> None:

    _raw, conn, repo = _sqlite_repo()
    try:
        assert repo.get("missing-id") is None
    finally:
        repo.close()
        conn.close()


def test_insert_if_absent_inserts_and_get_round_trips() -> None:
    raw, conn, repo = _sqlite_repo()
    try:
        snapshot = _make_snapshot()
        stored, inserted = repo.insert_if_absent(snapshot)
        assert inserted is True
        assert stored.snapshot_id == snapshot.snapshot_id
        loaded = repo.get(snapshot.snapshot_id)
        assert loaded is not None
        assert loaded.snapshot_id == snapshot.snapshot_id
        assert loaded.schema_version == SCHEMA_VERSION
        assert loaded.run_id == snapshot.run_id
        assert loaded.source_id == snapshot.source_id
        assert loaded.dedup_key == snapshot.dedup_key
        assert loaded.provider_entity_id == snapshot.provider_entity_id
        assert loaded.payload_sha256 == snapshot.payload_sha256
        assert dict(loaded.payload_json) == dict(snapshot.payload_json)
        assert loaded.source_url == snapshot.source_url
        assert loaded.collected_at == snapshot.collected_at
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 1
    finally:
        repo.close()
        conn.close()


def test_insert_if_absent_duplicate_equivalent_returns_existing_false() -> None:
    raw, conn, repo = _sqlite_repo()
    try:
        snapshot = _make_snapshot()
        first, first_inserted = repo.insert_if_absent(snapshot)
        second, second_inserted = repo.insert_if_absent(snapshot)
        assert first_inserted is True
        assert second_inserted is False
        assert second.snapshot_id == first.snapshot_id
        assert second.payload_sha256 == first.payload_sha256
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 1
    finally:
        repo.close()
        conn.close()


def test_insert_if_absent_collected_at_drift_is_duplicate_preserves_original() -> None:
    """Same snapshot_id + non-time fields equal + different collected_at → duplicate.

    collected_at is retry metadata only: return existing row, never overwrite the
    original stored timestamp, never raise EconomicSnapshotContentConflict.
    """
    raw, conn, repo = _sqlite_repo()
    try:
        original_at = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        retry_at = datetime(2026, 7, 22, 13, 30, tzinfo=UTC)
        original = _make_snapshot(collected_at=original_at)
        retry = _make_snapshot(collected_at=retry_at)
        assert original.snapshot_id == retry.snapshot_id
        assert original.collected_at != retry.collected_at

        first, first_inserted = repo.insert_if_absent(original)
        assert first_inserted is True
        assert first.collected_at == original_at

        second, second_inserted = repo.insert_if_absent(retry)
        assert second_inserted is False
        assert second.snapshot_id == first.snapshot_id
        assert second.collected_at == original_at
        assert second.collected_at != retry_at

        loaded = repo.get(original.snapshot_id)
        assert loaded is not None
        assert loaded.collected_at == original_at
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 1
        # Re-load after retry proves zero UPDATE of the stored timestamp.
        reloaded = repo.get(original.snapshot_id)
        assert reloaded is not None
        assert reloaded.collected_at == original_at
        assert reloaded.collected_at == second.collected_at
    finally:
        repo.close()
        conn.close()


def test_insert_if_absent_same_id_different_content_raises_conflict() -> None:
    from app.opportunity.economic_repository import EconomicSnapshotContentConflict

    raw, conn, repo = _sqlite_repo()
    try:
        original = _make_snapshot()
        repo.insert_if_absent(original)
        # Same snapshot_id (forced) but different payload content fields
        conflict = EconomicSnapshotRow(
            snapshot_id=original.snapshot_id,
            schema_version=SCHEMA_VERSION,
            run_id=original.run_id,
            source_id=original.source_id,
            dedup_key="protocol:other-key",
            provider_entity_id=original.provider_entity_id,
            payload_sha256=original.payload_sha256,
            payload_json=original.payload_json,
            source_url=original.source_url,
            collected_at=original.collected_at,
        )
        with pytest.raises(EconomicSnapshotContentConflict):
            repo.insert_if_absent(conflict)
        # Rollback + zero UPDATE: still exactly one row with original dedup_key
        row = raw.execute(
            "SELECT dedup_key FROM opportunity_economic_snapshots WHERE snapshot_id = ?",
            (original.snapshot_id,),
        ).fetchone()
        assert row["dedup_key"] == original.dedup_key
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 1
    finally:
        repo.close()
        conn.close()


def test_cross_run_same_payload_inserts_two_rows() -> None:
    raw, conn, repo = _sqlite_repo()
    try:
        day1 = _make_snapshot(run_id="daily:2026-07-22:defillama")
        day2 = _make_snapshot(run_id="daily:2026-07-23:defillama")
        assert day1.snapshot_id != day2.snapshot_id
        _, inserted1 = repo.insert_if_absent(day1)
        _, inserted2 = repo.insert_if_absent(day2)
        assert inserted1 is True
        assert inserted2 is True
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 2
    finally:
        repo.close()
        conn.close()


def test_blank_dedup_key_rejected_by_model() -> None:
    with pytest.raises(ValidationError):
        _make_snapshot(dedup_key="   ")
    with pytest.raises(ValidationError):
        _make_snapshot(dedup_key="")


def test_blank_dedup_key_rejected_by_db_check() -> None:
    raw, conn, repo = _sqlite_repo()
    try:
        # Bypass model validation via direct SQL to prove CHECK constraint
        with pytest.raises(sqlite3.IntegrityError):
            raw.execute(
                """
                INSERT INTO opportunity_economic_snapshots (
                    snapshot_id, schema_version, run_id, source_id, dedup_key,
                    provider_entity_id, payload_sha256, payload_json, source_url, collected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "sid-blank",
                    SCHEMA_VERSION,
                    "run-1",
                    "defillama",
                    "   ",
                    "entity-1",
                    "a" * 64,
                    "{}",
                    "https://example.com",
                    "2026-07-22 12:00:00+00:00",
                ),
            )
    finally:
        repo.close()
        conn.close()


def test_dedup_key_leading_trailing_spaces_preserved() -> None:
    raw, conn, repo = _sqlite_repo()
    try:
        snapshot = _make_snapshot(dedup_key="  spaced-key  ")
        stored, inserted = repo.insert_if_absent(snapshot)
        assert inserted is True
        assert stored.dedup_key == "  spaced-key  "
        loaded = repo.get(snapshot.snapshot_id)
        assert loaded is not None
        assert loaded.dedup_key == "  spaced-key  "
        db_value = raw.execute(
            "SELECT dedup_key FROM opportunity_economic_snapshots WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()[0]
        assert db_value == "  spaced-key  "
    finally:
        repo.close()
        conn.close()


def test_external_connection_not_closed_by_repository_close() -> None:
    _raw, conn, repo = _sqlite_repo()
    try:
        snapshot = _make_snapshot()
        repo.insert_if_absent(snapshot)
        repo.close()
        # External conn must still accept execute after repository.close()
        row = conn.execute(
            "SELECT snapshot_id FROM opportunity_economic_snapshots WHERE snapshot_id = ?",
            (snapshot.snapshot_id,),
        ).fetchone()
        assert row is not None
        assert row["snapshot_id"] == snapshot.snapshot_id
    finally:
        conn.close()


def test_repository_context_manager_closes_only_owned_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.opportunity import economic_repository as repo_module
    from app.opportunity.economic_repository import EconomicSnapshotRepository

    events: list[str] = []

    class _Owned(DbConnection):
        def close(self) -> None:  # type: ignore[override]
            events.append("close")
            super().close()

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    owned = _Owned(raw, kind="sqlite")
    init_db(owned)
    monkeypatch.setattr(repo_module, "_as_db_connection", lambda conn=None: (owned, True))

    with EconomicSnapshotRepository(None) as repo:
        assert isinstance(repo, EconomicSnapshotRepository)
    assert events == ["close"]


def test_insert_if_absent_conflict_on_payload_json_field() -> None:
    from app.opportunity.economic_repository import EconomicSnapshotContentConflict

    _raw, conn, repo = _sqlite_repo()
    try:
        original = _make_snapshot()
        repo.insert_if_absent(original)
        conflict = EconomicSnapshotRow(
            snapshot_id=original.snapshot_id,
            schema_version=SCHEMA_VERSION,
            run_id=original.run_id,
            source_id=original.source_id,
            dedup_key=original.dedup_key,
            provider_entity_id=original.provider_entity_id,
            payload_sha256=original.payload_sha256,
            payload_json={"tvl": 999, "change_7d": 0.05, "change_7d_unit": "ratio"},
            source_url=original.source_url,
            collected_at=original.collected_at,
        )
        with pytest.raises(EconomicSnapshotContentConflict):
            repo.insert_if_absent(conflict)
        loaded = repo.get(original.snapshot_id)
        assert loaded is not None
        assert dict(loaded.payload_json) == dict(original.payload_json)
    finally:
        repo.close()
        conn.close()


# --- PostgreSQL-shaped integrity path (psycopg3 sqlstate=23505; no live network/DB) ---


class _PgUniqueViolation(Exception):  # noqa: N818 — psycopg stand-in name
    """Minimal stand-in for psycopg.errors.UniqueViolation (sqlstate only)."""

    def __init__(self, message: str = "duplicate key value violates unique constraint") -> None:
        super().__init__(message)
        self.sqlstate = "23505"


class _PgCheckViolation(Exception):  # noqa: N818 — psycopg stand-in name
    """Unrelated check violation must not be treated as unique-integrity conflict."""

    def __init__(self, message: str = "check constraint violated") -> None:
        super().__init__(message)
        self.sqlstate = "23514"


class _PgFakeRaw:
    """In-memory table that raises UniqueViolation (sqlstate=23505) on PK clash.

    Matches DbConnection postgres path: cursor() returns self; execute result is
    ignored; fetchone is called on the cursor object.
    """

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self._rows: dict[str, dict[str, Any]] = {}
        self._pending: dict[str, dict[str, Any]] | None = None
        self._last_fetch: dict[str, Any] | None = None

    def cursor(self) -> Any:
        return self

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        sql_n = " ".join(sql.split()).lower()
        self._last_fetch = None
        if sql_n.startswith("insert into opportunity_economic_snapshots"):
            row = {
                "snapshot_id": params[0],
                "schema_version": params[1],
                "run_id": params[2],
                "source_id": params[3],
                "dedup_key": params[4],
                "provider_entity_id": params[5],
                "payload_sha256": params[6],
                "payload_json": params[7],
                "source_url": params[8],
                "collected_at": params[9],
            }
            if params[0] in self._rows:
                raise _PgUniqueViolation()
            # Stage until commit (mirrors transactional insert).
            if self._pending is None:
                self._pending = dict(self._rows)
            self._pending[params[0]] = row
            return
        if "from opportunity_economic_snapshots where snapshot_id" in sql_n:
            self._last_fetch = self._rows.get(params[0])
            return
        raise AssertionError(f"unexpected SQL in PG fake: {sql!r}")

    def fetchone(self) -> dict[str, Any] | None:
        return self._last_fetch

    def commit(self) -> None:
        self._events.append("commit")
        if self._pending is not None:
            self._rows = self._pending
            self._pending = None

    def rollback(self) -> None:
        self._events.append("rollback")
        self._pending = None

    def close(self) -> None:
        self._events.append("close")


def _pg_repo(events: list[str] | None = None):
    from app.opportunity.economic_repository import EconomicSnapshotRepository

    log = events if events is not None else []
    raw = _PgFakeRaw(log)
    conn = DbConnection(raw, kind="postgres")
    return raw, conn, EconomicSnapshotRepository(conn), log


def test_is_integrity_error_prefers_sqlstate_23505_not_check_violations() -> None:
    from app.opportunity.economic_repository import _is_integrity_error

    assert _is_integrity_error(_PgUniqueViolation()) is True

    class _LegacyPgcode(Exception):  # noqa: N818 — pgcode attribute probe
        pgcode = "23505"

    assert _is_integrity_error(_LegacyPgcode()) is True
    assert _is_integrity_error(_PgCheckViolation()) is False

    class _NamedOnly(Exception):  # noqa: N818 — class-name integrity probe
        pass

    class UniqueViolation(_NamedOnly):
        pass

    assert _is_integrity_error(UniqueViolation()) is True


def test_pg_insert_if_absent_duplicate_equivalent_via_sqlstate_23505() -> None:
    raw, conn, repo, events = _pg_repo()
    try:
        snapshot = _make_snapshot()
        first, first_inserted = repo.insert_if_absent(snapshot)
        second, second_inserted = repo.insert_if_absent(snapshot)
        assert first_inserted is True
        assert second_inserted is False
        assert second.snapshot_id == first.snapshot_id
        assert second.dedup_key == first.dedup_key
        assert "rollback" in events
        assert events.count("commit") == 1
        assert len(raw._rows) == 1
    finally:
        repo.close()
        conn.close()


def test_pg_insert_if_absent_collected_at_drift_is_duplicate_preserves_original() -> None:
    """PG parity: collected_at-only drift is duplicate; original timestamp stays."""
    raw, conn, repo, events = _pg_repo()
    try:
        original_at = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
        retry_at = datetime(2026, 7, 22, 13, 30, tzinfo=UTC)
        original = _make_snapshot(collected_at=original_at)
        retry = _make_snapshot(collected_at=retry_at)
        assert original.snapshot_id == retry.snapshot_id

        _first, first_inserted = repo.insert_if_absent(original)
        assert first_inserted is True

        second, second_inserted = repo.insert_if_absent(retry)
        assert second_inserted is False
        assert second.collected_at == original_at
        assert second.collected_at != retry_at
        assert "rollback" in events
        assert events.count("commit") == 1
        assert len(raw._rows) == 1
        assert raw._rows[original.snapshot_id]["collected_at"] == original_at
        loaded = repo.get(original.snapshot_id)
        assert loaded is not None
        assert loaded.collected_at == original_at
    finally:
        repo.close()
        conn.close()


def test_pg_insert_if_absent_content_conflict_via_sqlstate_23505_rolls_back() -> None:
    from app.opportunity.economic_repository import EconomicSnapshotContentConflict

    raw, conn, repo, events = _pg_repo()
    try:
        original = _make_snapshot()
        repo.insert_if_absent(original)
        conflict = EconomicSnapshotRow(
            snapshot_id=original.snapshot_id,
            schema_version=SCHEMA_VERSION,
            run_id=original.run_id,
            source_id=original.source_id,
            dedup_key="protocol:other-key",
            provider_entity_id=original.provider_entity_id,
            payload_sha256=original.payload_sha256,
            payload_json=original.payload_json,
            source_url=original.source_url,
            collected_at=original.collected_at,
        )
        with pytest.raises(EconomicSnapshotContentConflict):
            repo.insert_if_absent(conflict)
        assert "rollback" in events
        # Original content preserved; no UPDATE / no second row.
        assert len(raw._rows) == 1
        assert raw._rows[original.snapshot_id]["dedup_key"] == original.dedup_key
        loaded = repo.get(original.snapshot_id)
        assert loaded is not None
        assert loaded.dedup_key == original.dedup_key
    finally:
        repo.close()
        conn.close()


# ── Task 5: dual-condition identity + list_by_identity ────────────


def _seed_project(conn: Any, project_id: str, name: str = "Example") -> None:
    conn.execute(
        "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
        (project_id, name, "test"),
    )
    conn.commit()


def _seed_raw(
    conn: Any,
    *,
    raw_id: str,
    source_id: str,
    dedup_key: str,
    project_id: str | None,
) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_id,
            source_id,
            dedup_key,
            "{}",
            "2026-07-22 12:00:00+00:00",
            0.5,
            project_id,
        ),
    )
    conn.commit()


def test_find_linked_project_id_dual_condition_and_list_by_identity() -> None:
    _raw, conn, repo = _sqlite_repo()
    try:
        # Combo 1: no raw row → None
        assert repo.find_linked_project_id("defillama", "protocol:missing") is None

        # Combo 2: raw exists, project_id empty/null → None
        _seed_raw(
            conn,
            raw_id="raw-empty",
            source_id="defillama",
            dedup_key="protocol:empty-link",
            project_id=None,
        )
        assert repo.find_linked_project_id("defillama", "protocol:empty-link") is None

        # Combo 3: project_id non-empty but projects.id missing → None
        _seed_raw(
            conn,
            raw_id="raw-orphan",
            source_id="defillama",
            dedup_key="protocol:orphan",
            project_id="nonexistent-project",
        )
        assert repo.find_linked_project_id("defillama", "protocol:orphan") is None

        # Combo 4: both conditions satisfied → exact project_id
        _seed_project(conn, "proj-linked")
        _seed_raw(
            conn,
            raw_id="raw-linked",
            source_id="defillama",
            dedup_key="protocol:example",
            project_id="proj-linked",
        )
        assert repo.find_linked_project_id("defillama", "protocol:example") == "proj-linked"

        # Same symbol/entity name but different dedup_key → no fuzzy link
        _seed_raw(
            conn,
            raw_id="raw-other-dedup",
            source_id="defillama",
            dedup_key="protocol:example-other",
            project_id="proj-linked",
        )
        assert repo.find_linked_project_id("defillama", "protocol:example-other") == "proj-linked"
        assert repo.find_linked_project_id("defillama", "protocol:not-that-key") is None

        # list_by_identity isolates by (source_id, dedup_key)
        snap_a = _make_snapshot(dedup_key="protocol:example", provider_entity_id="ent-a")
        snap_b = _make_snapshot(
            dedup_key="protocol:example-other",
            provider_entity_id="ent-b",
            run_id="daily:2026-07-22:defillama-b",
        )
        snap_c = _make_snapshot(
            source_id="coingecko",
            dedup_key="protocol:example",
            provider_entity_id="ent-c",
            run_id="daily:2026-07-22:coingecko",
            payload={"market_cap": 1, "current_price": 2, "total_volume": 3},
        )
        repo.insert_if_absent(snap_a)
        repo.insert_if_absent(snap_b)
        repo.insert_if_absent(snap_c)

        listed = repo.list_by_identity("defillama", "protocol:example")
        assert isinstance(listed, tuple)
        assert len(listed) == 1
        assert listed[0].snapshot_id == snap_a.snapshot_id
        assert listed[0].dedup_key == "protocol:example"

        listed_other = repo.list_by_identity("defillama", "protocol:example-other")
        assert len(listed_other) == 1
        assert listed_other[0].snapshot_id == snap_b.snapshot_id

        # No cross-source leakage for same dedup_key string
        listed_cg = repo.list_by_identity("coingecko", "protocol:example")
        assert len(listed_cg) == 1
        assert listed_cg[0].snapshot_id == snap_c.snapshot_id

        empty = repo.list_by_identity("defillama", "protocol:never")
        assert empty == ()
    finally:
        repo.close()
        conn.close()


# ── Task 6: source_ids_by_snapshot_id batch lookup ────────────


def test_source_ids_by_snapshot_id_empty_returns_empty_zero_query() -> None:
    _raw, conn, repo = _sqlite_repo()
    try:
        execute_calls: list[str] = []
        original_execute = conn.execute

        def _counting_execute(sql: str, params: tuple[Any, ...] = ()) -> Any:
            execute_calls.append(sql)
            return original_execute(sql, params)

        conn.execute = _counting_execute  # type: ignore[method-assign]
        result = repo.source_ids_by_snapshot_id([])
        assert result == {}
        assert execute_calls == []
        result_empty_set = repo.source_ids_by_snapshot_id(set())
        assert result_empty_set == {}
        assert execute_calls == []
    finally:
        repo.close()
        conn.close()


def test_source_ids_by_snapshot_id_batch_maps_present_omits_unknown() -> None:
    _raw, conn, repo = _sqlite_repo()
    try:
        snap_dl = _make_snapshot(
            source_id="defillama",
            dedup_key="protocol:batch-a",
            provider_entity_id="ent-batch-a",
        )
        snap_cg = _make_snapshot(
            source_id="coingecko",
            dedup_key="coin:batch-b",
            provider_entity_id="ent-batch-b",
            run_id="daily:2026-07-22:coingecko",
            payload={"market_cap": 1, "current_price": 2, "total_volume": 3},
        )
        repo.insert_if_absent(snap_dl)
        repo.insert_if_absent(snap_cg)

        execute_calls: list[str] = []
        original_execute = conn.execute

        def _counting_execute(sql: str, params: tuple[Any, ...] = ()) -> Any:
            execute_calls.append(sql)
            return original_execute(sql, params)

        conn.execute = _counting_execute  # type: ignore[method-assign]

        ids = [snap_dl.snapshot_id, "missing-snapshot-id", snap_cg.snapshot_id]
        result = repo.source_ids_by_snapshot_id(ids)

        assert len(execute_calls) == 1
        sql = " ".join(execute_calls[0].split()).lower()
        assert "from opportunity_economic_snapshots" in sql
        assert "snapshot_id" in sql
        assert "source_id" in sql
        assert " in (" in sql

        assert result == {
            snap_dl.snapshot_id: "defillama",
            snap_cg.snapshot_id: "coingecko",
        }
        assert "missing-snapshot-id" not in result
    finally:
        repo.close()
        conn.close()


def test_source_ids_by_snapshot_id_single_id_one_query() -> None:
    _raw, conn, repo = _sqlite_repo()
    try:
        snap = _make_snapshot(provider_entity_id="ent-single-batch")
        repo.insert_if_absent(snap)

        execute_calls: list[str] = []
        original_execute = conn.execute

        def _counting_execute(sql: str, params: tuple[Any, ...] = ()) -> Any:
            execute_calls.append(sql)
            return original_execute(sql, params)

        conn.execute = _counting_execute  # type: ignore[method-assign]
        result = repo.source_ids_by_snapshot_id([snap.snapshot_id])
        assert len(execute_calls) == 1
        assert result == {snap.snapshot_id: "defillama"}
    finally:
        repo.close()
        conn.close()
