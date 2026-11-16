"""PG 兼容性回归：所有 INSERT 返回 id 的路径不得依赖 cursor.lastrowid。

psycopg3 删除了 cursor.lastrowid（见 app/db.py::insert_returning_id 的注释，
roi/participation/feedback 路由均已改走该 helper）。本文件用 psycopg3 风格
假连接（游标没有 lastrowid 属性、只有 RETURNING 能带回 id）钉住契约：
这些仓储方法在 DB_BACKEND=postgres 下必须照常返回新行 id。

修复前直接读 cursor.lastrowid 的 8 处（audit_logs / metrics /
llm_eval_changelog / quarantine / project_history / prompt_versions /
weight_changelog / archive_runs）在 PG 上全部 AttributeError。

Reference:
- ADR-004 双后端支持
- app/db.py insert_returning_id（权威实现）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.calibration import record_candidate
from app.db import DbConnection
from app.repositories.archive_runs import ArchiveRunRepository
from app.repositories.v2 import (
    AuditLogRepository,
    LLMEvalRepository,
    MetricsRepository,
    ProjectHistoryRepository,
    PromptVersionsRepository,
    QuarantineRepository,
)


class _FakePgCursor:
    """模拟 psycopg3 游标：execute() 返回游标自身，fetchone() 读 RETURNING 结果。"""

    def __init__(self, conn: _FakePgRaw) -> None:
        self._conn = conn
        self._rows: list[tuple[int, ...]] = []

    def execute(self, sql: str, params: Any = ()) -> _FakePgCursor:
        self._conn.executed.append((sql, tuple(params)))
        if "RETURNING" in sql.upper():
            row_id = self._conn._next_id
            self._conn._next_id += 1
            self._rows = [(row_id,)]
        else:
            self._rows = []
        return self

    def fetchone(self) -> tuple[int, ...] | None:
        return self._rows[0] if self._rows else None


class _FakePgRaw:
    """psycopg3 风格假连接。

    只有包含 RETURNING 的语句会带回自增 id；其余语句返回空结果。
    记录 (sql, params) 以便断言 RETURNING 确实出现在发出的 SQL 里。
    """

    def __init__(self) -> None:
        self._next_id = 100
        self.executed: list[tuple[str, tuple[Any, ...]]] = []

    def commit(self) -> None:
        pass

    def rollback(self) -> None:
        pass

    def close(self) -> None:
        pass

    def cursor(self) -> _FakePgCursor:
        return _FakePgCursor(self)


def _pg_conn() -> tuple[DbConnection, _FakePgRaw]:
    raw = _FakePgRaw()
    return DbConnection(raw, kind="postgres"), raw


# ── app/repositories/v2.py ──────────────────────


def test_audit_log_insert_returns_id_on_pg() -> None:
    conn, raw = _pg_conn()
    log_id = AuditLogRepository(conn).insert(action="run", user="admin")
    assert log_id == 100
    assert "RETURNING ID" in raw.executed[0][0].upper()


def test_audit_log_insert_ids_advance_on_pg() -> None:
    conn, _ = _pg_conn()
    repo = AuditLogRepository(conn)
    first = repo.insert(action="run", user="a")
    second = repo.insert(action="run", user="b")
    assert (first, second) == (100, 101)


def test_metrics_insert_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    metric_id = MetricsRepository(conn).insert(run_id="run-1", metric_name="completeness", metric_value=0.95)
    assert metric_id == 100


def test_llm_eval_insert_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    eval_id = LLMEvalRepository(conn).insert(
        eval_date="2026-11-13",
        sample_count=10,
        rule_accuracy=0.9,
        llm_accuracy=0.8,
        llm_cost_usd=0.01,
        decision="keep",
    )
    assert eval_id == 100


def test_quarantine_insert_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    qid = QuarantineRepository(conn).insert(raw_data="{}", failure_reason="dedup_conflict")
    assert qid == 100


def test_project_history_insert_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    hid = ProjectHistoryRepository(conn).insert(project_id="p1", run_id="run-1", snapshot="{}")
    assert hid == 100


def test_prompt_version_insert_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    pid = PromptVersionsRepository(conn).insert(
        agent_name="narrative", prompt_key="k", version="v1", content="c", created_by="admin"
    )
    assert pid == 100


def test_prompt_version_default_clear_uses_returned_id_on_pg() -> None:
    """is_default=True 时排除自身用的必须是 RETURNING 回来的 id，而非 lastrowid。"""
    conn, raw = _pg_conn()
    pid = PromptVersionsRepository(conn).insert(
        agent_name="narrative",
        prompt_key="k",
        version="v1",
        content="c",
        created_by="admin",
        is_default=True,
    )
    assert pid == 100
    update_params = [params for sql, params in raw.executed if "UPDATE prompt_versions" in sql]
    assert update_params, "is_default=True 应触发 _clear_other_defaults 的 UPDATE"
    assert update_params[0][-1] == 100, "UPDATE ... id != ? 的排除 id 必须来自 RETURNING"


# ── app/calibration.py ──────────────────────────


def test_record_candidate_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    changelog_id = record_candidate(
        conn,
        from_version="v1.1",
        to_version="v1.2",
        weights={"signal": 0.18},
        sample_size=3,
        metrics={"j": 0.5},
    )
    assert changelog_id == 100


# ── app/repositories/archive_runs.py ────────────


def test_archive_run_record_returns_id_on_pg() -> None:
    conn, _ = _pg_conn()
    run_id = ArchiveRunRepository(conn).record(
        started_at=datetime.now(UTC),
        trigger="scheduler",
        status="success",
    )
    assert run_id == 100


def test_archive_run_record_rejects_unknown_trigger_on_pg() -> None:
    conn, _ = _pg_conn()
    with pytest.raises(ValueError, match="Unknown trigger"):
        ArchiveRunRepository(conn).record(
            started_at=datetime.now(UTC),
            trigger="cron",
            status="success",
        )
