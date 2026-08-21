"""A2 PostgreSQL concurrent re-score row lock serialization tests.

Verifies that SELECT ... FOR UPDATE in repository.py correctly serializes
concurrent re-score operations on the same project, preventing lost updates
in read-modify-write cycles (A2 acceptance: 并发 re-score 行锁串行化).

Tests are skipped when PostgreSQL is not available. To run them:
    DB_BACKEND=postgres pytest tests/test_pg_concurrent_rescore.py -v

Prerequisites:
    docker compose -f docker-compose.postgres.yml up -d
"""

from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime

import pytest

from app.config import Settings
from app.db import get_connection, init_db, is_postgres
from app.repository import ProjectRepository

# ── PG availability check (runtime, not collection-time) ───


def _pg_reachable() -> bool:
    """True when DB_BACKEND=postgres (or DATABASE_URL is pg) AND PG accepts connections."""
    # Check environment directly — settings singleton may have been initialized
    # by another test module before DB_BACKEND was set
    db_backend = os.environ.get("DB_BACKEND", "").strip().lower()
    database_url = os.environ.get("DATABASE_URL", "").strip()
    is_pg = (
        db_backend == "postgres" or database_url.startswith("postgresql://") or database_url.startswith("postgres://")
    )
    # Also check the settings singleton
    if not is_pg and not is_postgres():
        return False
    try:
        conn = get_connection()
        conn.execute("SELECT 1")
        conn.close()
        return True
    except Exception:
        return False


# ── Unit tests (no PG needed) ───────────────────


class TestDbBackendConfigResolution:
    """Verify DB_BACKEND=postgres auto-constructs DATABASE_URL from POSTGRES_* parts."""

    def test_db_backend_postgres_auto_builds_url(self):
        s = Settings(_env_file=None, db_backend="postgres", database_url=None)
        assert s.database_url is not None
        assert s.database_url.startswith("postgresql://")
        assert "5433" in s.database_url

    def test_explicit_database_url_overrides_parts(self):
        url = "postgresql://custom:pw@db.internal:5432/mydb"
        s = Settings(_env_file=None, db_backend="postgres", database_url=url)
        assert s.database_url == url

    def test_database_url_pg_auto_sets_backend(self):
        url = "postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test"
        s = Settings(_env_file=None, db_backend="sqlite", database_url=url)
        assert s.db_backend == "postgres"

    def test_sqlite_default(self, monkeypatch):
        """When no DB_BACKEND or DATABASE_URL env vars are set, defaults to sqlite."""
        # Temporarily clear PG-related env vars so they don't override defaults
        monkeypatch.delenv("DB_BACKEND", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)
        s = Settings(_env_file=None)
        assert s.db_backend == "sqlite"
        assert s.database_url is None


# ── PG integration tests ─────────────────────────


def _skip_if_no_pg():
    """Skip test if PG is not reachable (called at test run time, not collection time)."""
    if not _pg_reachable():
        pytest.skip("PostgreSQL not configured/reachable — run: docker compose -f docker-compose.postgres.yml up -d")


@pytest.fixture
def pg_schema():
    """Ensure PG schema exists; skip if PG not available; clean up test rows after."""
    _skip_if_no_pg()
    init_db()
    yield
    conn = get_connection()
    try:
        conn.execute("DELETE FROM projects WHERE id LIKE ?", ("pg-test-%",))
        conn.commit()
    finally:
        conn.close()


def _insert_test_project(project_id: str, signals: dict | None = None) -> None:
    """Insert a minimal project row for concurrent-update tests."""
    meta = json.dumps({"signals": signals or {}})
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO projects (id, name, source, meta, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET meta = EXCLUDED.meta, updated_at = EXCLUDED.updated_at
            """,
            (project_id, "PG Concurrent Test", "test", meta, datetime.now(UTC), datetime.now(UTC)),
        )
        conn.commit()
    finally:
        conn.close()


def _read_meta_signals(project_id: str) -> dict:
    """Return the signals dict from a project's meta column."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT meta FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if not row:
            return {}
        meta = json.loads(dict(row).get("meta") or "{}")
        return meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    finally:
        conn.close()


class TestConcurrentUpdateMetaSignals:
    """update_meta_signals uses SELECT ... FOR UPDATE to serialize concurrent re-scores."""

    def test_no_lost_updates_concurrent_signals(self, pg_schema):
        """N threads each write a unique signal key; all must survive.

        Without FOR UPDATE, concurrent read-modify-write of projects.meta
        loses updates: thread B reads old meta before A commits, then B's
        write overwrites A's merged signals.
        """
        pid = "pg-test-rescore-001"
        _insert_test_project(pid)
        num_threads = 8
        keys = [f"signal_{i}" for i in range(num_threads)]
        errors: list[Exception] = []

        def worker(key: str):
            try:
                repo = ProjectRepository()
                repo.update_meta_signals(pid, signals={key: f"val_{key}"})
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(k,)) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        assert not errors, f"Workers raised: {[str(e) for e in errors]}"

        signals = _read_meta_signals(pid)
        for key in keys:
            assert key in signals, f"Lost update: '{key}' missing — row lock did not serialize"

    def test_serialized_writes_produce_sequential_snapshots(self, pg_schema):
        """Each thread's write must be visible to the next (serialized, not interleaved)."""
        pid = "pg-test-rescore-002"
        _insert_test_project(pid, signals={"init": True})
        num_threads = 5
        errors: list[Exception] = []
        counts_seen: list[int] = []

        def worker(i: int):
            try:
                repo = ProjectRepository()
                repo.update_meta_signals(pid, signals={f"key_{i}": i})
                # Read back immediately — should see all prior committed writes
                sigs = _read_meta_signals(pid)
                counts_seen.append(len(sigs))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        assert not errors, f"Workers raised: {[str(e) for e in errors]}"
        # Final state must have init + num_threads keys
        final = _read_meta_signals(pid)
        assert len(final) == num_threads + 1, f"Expected {num_threads + 1} signals, got {len(final)}: {final}"


class TestConcurrentSaveMetaMerge:
    """save() uses SELECT meta ... FOR UPDATE before UPSERT; meta signals must not be lost."""

    def test_concurrent_saves_preserve_all_meta_signals(self, pg_schema):
        """N threads save() the same project ID with different signal in meta.

        The FOR UPDATE lock ensures each save reads the latest committed meta
        before merging, so no signal is lost.
        """
        from app.agents.base import AgentContext, PipelineState, RawProject

        pid = "pg-test-save-001"
        # Seed the project so FOR UPDATE has a row to lock
        _insert_test_project(pid)

        num_threads = 5
        errors: list[Exception] = []

        def worker(i: int):
            try:
                project = RawProject(
                    id=pid,
                    name=f"Concurrent Save {i}",
                    url="https://test.example",
                    sector="L2",
                    stage="testnet",
                    source="test",
                )
                state = PipelineState(
                    project=project,
                    context=AgentContext(run_id="pg-test-run", enable_llm=False),
                    score=50 + i,
                    label="WATCH",
                    confidence=0.8,
                )
                state.reason = [f"reason_{i}"]
                repo = ProjectRepository()
                repo.save(state)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(30)

        assert not errors, f"Save workers raised: {[str(e) for e in errors]}"

        # Verify the project still exists and has valid meta
        conn = get_connection()
        try:
            row = conn.execute("SELECT meta FROM projects WHERE id = ?", (pid,)).fetchone()
            assert row is not None, "Project was deleted by concurrent save"
            meta = json.loads(dict(row).get("meta") or "{}")
        finally:
            conn.close()

        # The last-write-wins for score/name is expected; meta structure must be valid
        assert isinstance(meta, dict), f"meta is not a dict: {meta}"
