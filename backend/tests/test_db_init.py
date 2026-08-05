"""Focused transaction-ordering tests for database schema initialization."""

from __future__ import annotations

import sqlite3
import warnings
from datetime import UTC, date, datetime
from typing import Any

import pytest

from app import db as db_module
from app.db import DbConnection, init_db


class _PostgresCursor:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._events.append(("execute", " ".join(sql.split()), params))

    def fetchone(self) -> dict[str, int]:
        # Existing columns keep this fake focused on transaction ordering.
        return {"exists": 1}

    def close(self) -> None:
        # 真实 psycopg 游标具备 close()；executescript 会显式关闭以防泄漏。
        # 这里保持 no-op，不记录事件以免影响顺序断言。
        return None


class _PostgresRawConnection:
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        self._events = events

    def cursor(self) -> _PostgresCursor:
        return _PostgresCursor(self._events)

    def commit(self) -> None:
        self._events.append(("commit",))

    def rollback(self) -> None:
        self._events.append(("rollback",))

    def close(self) -> None:
        self._events.append(("close",))


class _RecordingPostgresConnection(DbConnection):
    def __init__(self, events: list[tuple[Any, ...]]) -> None:
        super().__init__(_PostgresRawConnection(events), kind="postgres")
        self._events = events
        self._script_count = 0
        self.fail_script: int | None = None

    def executescript(self, script: str) -> None:
        self._script_count += 1
        self._events.append(("executescript", self._script_count))
        if self._script_count == self.fail_script:
            raise RuntimeError("synthetic migration failure")
        super().executescript(script)


def test_sqlite_explicitly_serializes_date_parameters_without_deprecated_adapters() -> None:
    raw = sqlite3.connect(":memory:")
    connection = DbConnection(raw, kind="sqlite")
    connection.execute("CREATE TABLE samples (created_at TEXT, day TEXT)")
    created_at = datetime(2026, 7, 15, 12, 30, tzinfo=UTC)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            connection.execute(
                "INSERT INTO samples (created_at, day) VALUES (?, ?)",
                (created_at, created_at.date()),
            )
            connection.executemany(
                "INSERT INTO samples (created_at, day) VALUES (?, ?)",
                [(created_at, date(2026, 7, 16))],
            )

        rows = connection.execute("SELECT created_at, day FROM samples ORDER BY day").fetchall()
    finally:
        connection.close()

    assert rows == [
        ("2026-07-15 12:30:00+00:00", "2026-07-15"),
        ("2026-07-15 12:30:00+00:00", "2026-07-16"),
    ]


def test_raw_sqlite_connections_use_explicit_application_datetime_adapters() -> None:
    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE samples (created_at TEXT, day TEXT)")
    created_at = datetime(2026, 7, 15, 12, 30, tzinfo=UTC)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", DeprecationWarning)
            raw.execute(
                "INSERT INTO samples (created_at, day) VALUES (?, ?)",
                (created_at, created_at.date()),
            )
        row = raw.execute("SELECT created_at, day FROM samples").fetchone()
    finally:
        raw.close()

    assert row == ("2026-07-15 12:30:00+00:00", "2026-07-15")


def test_postgres_advisory_lock_precedes_all_ddl_and_commit() -> None:
    events: list[tuple[Any, ...]] = []
    connection = _RecordingPostgresConnection(events)

    init_db(connection)

    lock_event = (
        "execute",
        "SELECT pg_advisory_xact_lock(%s)",
        (db_module.POSTGRES_INIT_ADVISORY_LOCK_ID,),
    )
    lock_index = events.index(lock_event)
    first_script_index = events.index(("executescript", 1))
    index_script_index = events.index(("executescript", 2))
    commit_index = events.index(("commit",))

    assert lock_index < first_script_index < index_script_index < commit_index
    assert ("rollback",) not in events


def test_sqlite_init_does_not_acquire_postgres_advisory_lock(tmp_path) -> None:
    import sqlite3

    statements: list[str] = []

    class RecordingSQLiteConnection(DbConnection):
        def execute(self, sql: str, params=None):
            statements.append(" ".join(sql.split()))
            return super().execute(sql, params)

    raw = sqlite3.connect(tmp_path / "init.db")
    raw.row_factory = sqlite3.Row
    connection = RecordingSQLiteConnection(raw, kind="sqlite")
    try:
        init_db(connection)
    finally:
        connection.close()

    assert not any("pg_advisory" in statement.lower() for statement in statements)


def test_migration_failure_rolls_back_before_owned_connection_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    connection = _RecordingPostgresConnection(events)
    connection.fail_script = 2
    monkeypatch.setattr(db_module, "get_connection", lambda: connection)

    with pytest.raises(RuntimeError, match="synthetic migration failure"):
        init_db()

    assert ("commit",) not in events
    assert events[-2:] == [("rollback",), ("close",)]
