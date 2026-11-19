"""Phase 1 P0 阻断缺陷与 ADR-015 单调性修复回归测试。"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from psycopg._queries import _query2pg

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.eligibility import VETO_ALREADY_LAUNCHED, apply_eligibility_gate
from app.auth import issue_anonymous_token
from app.config import settings
from app.db import DbConnection, connection_scope, init_db
from app.main import create_app
from app.notify.evaluator import _exit_advisories_today
from app.opportunity.service import OpportunityService
from app.repositories.user import BlacklistedJtiRepository, UserRepository
from app.repository import ProjectRepository
from app.services.launch_review import HIDDEN_REASON_ALREADY_LAUNCHED, run_launch_review
from app.services.user_scope import owned_project_ids_where


class _DictRowPgCursor:
    """模拟 psycopg3 + dict_row 游标：只支持按列名键访问，下标 row[0] 必抛 KeyError(0)。"""

    def __init__(self, parent: _DictRowPgConn) -> None:
        self._parent = parent
        self._cur: sqlite3.Cursor | None = None
        self.rowcount = 0
        self.description: Any = None

    def execute(self, pg_sql: str, params: tuple[Any, ...] = ()) -> _DictRowPgCursor:
        # 1. 用真实 psycopg3 解析器校验 % 转义与 %s 占位符（未转义的 LIKE '%x%' 会当场抛错）
        _query2pg(pg_sql.encode("utf-8"), "utf-8")
        self._parent.executed_pg_sql.append(pg_sql)
        assert "INSERT OR REPLACE" not in pg_sql.upper()
        # 2. 还原回 SQLite 执行并包装成纯 dict 行，检验调用方是否误用 row[0]
        sqlite_sql = pg_sql.replace("%s", "?").replace("%%", "%")
        self._cur = self._parent._sqlite.execute(sqlite_sql, params)
        self.rowcount = self._cur.rowcount
        self.description = self._cur.description
        return self

    def _to_dict(self, row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(row)

    def fetchone(self) -> dict[str, Any] | None:
        return self._to_dict(self._cur.fetchone()) if self._cur is not None else None

    def fetchall(self) -> list[dict[str, Any]]:
        if self._cur is None:
            return []
        return [d for r in self._cur.fetchall() if (d := self._to_dict(r)) is not None]


class _DictRowPgConn:
    """用真实 SQLite 引擎承载查询，同时校验 PG 占位符语法并返回纯 dict 行。"""

    def __init__(self, raw_sqlite: sqlite3.Connection) -> None:
        self._sqlite = raw_sqlite
        self.executed_pg_sql: list[str] = []

    def cursor(self) -> _DictRowPgCursor:
        return _DictRowPgCursor(self)

    def commit(self) -> None:
        self._sqlite.commit()

    def rollback(self) -> None:
        self._sqlite.rollback()

    def close(self) -> None:
        self._sqlite.close()


class TestP01PostgresCompatibility:
    """P0-1：PostgreSQL 占位符 `%` 转义、dict_row、JTI UPSERT 与 Alembic 0002 兼容性。"""

    def test_pg_normalize_escapes_literal_percent_in_exit_advisories(self, tmp_path: Path) -> None:
        raw_sqlite = sqlite3.connect(str(tmp_path / "pg_sim.db"))
        raw_sqlite.row_factory = sqlite3.Row
        init_db(raw_sqlite)
        now_iso = datetime.now(UTC).isoformat()
        raw_sqlite.execute(
            "INSERT INTO projects (id, name, meta, updated_at) VALUES (?, ?, ?, ?)",
            ("dead-site", "DeadSite", json.dumps({"signals": {"site_alive": False}}), now_iso),
        )
        raw_sqlite.commit()

        pg_sim = DbConnection(_DictRowPgConn(raw_sqlite), kind="postgres")
        try:
            window = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            advisories = _exit_advisories_today(pg_sim, window)
            assert len(advisories) == 1
            assert advisories[0]["project_id"] == "dead-site"
        finally:
            pg_sim.close()

    def test_dict_row_no_key_error_zero_in_repositories_and_scope(self, tmp_path: Path) -> None:
        raw_sqlite = sqlite3.connect(str(tmp_path / "dict_row.db"))
        raw_sqlite.row_factory = sqlite3.Row
        init_db(raw_sqlite)
        raw_sqlite.execute("INSERT INTO users (id, email, password_hash, role) VALUES ('u1', 'a@b.com', 'h', 'admin')")
        raw_sqlite.execute("INSERT INTO watchlist (project_id, user_id) VALUES ('p-watch', 'u1')")
        raw_sqlite.commit()

        pg_sim = DbConnection(_DictRowPgConn(raw_sqlite), kind="postgres")
        try:
            assert UserRepository(pg_sim).count_users() == 1
            assert owned_project_ids_where(pg_sim, "watchlist", "u1", None) == {"p-watch"}

            jti_repo = BlacklistedJtiRepository(pg_sim)
            exp1 = datetime.now(UTC) + timedelta(hours=1)
            exp2 = datetime.now(UTC) + timedelta(hours=2)
            jti_repo.blacklist_jti("jti-1", exp1)
            jti_repo.blacklist_jti("jti-1", exp2)
            assert jti_repo.is_blacklisted("jti-1") is True
        finally:
            pg_sim.close()

    def test_alembic_0002_translates_autoincrement_for_postgresql(self) -> None:
        import importlib.util

        mig_path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0002_v2_new_tables.py"
        spec = importlib.util.spec_from_file_location("mig_0002", mig_path)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        executed: list[str] = []

        class _FakeBind:
            dialect = MagicMock(name="postgresql")

            def execute(self, clause: Any) -> None:
                executed.append(str(clause))

        _FakeBind.dialect.name = "postgresql"
        orig_get_bind = mod.op.get_bind
        mod.op.get_bind = lambda: _FakeBind()
        try:
            mod.upgrade()
        finally:
            mod.op.get_bind = orig_get_bind

        assert executed
        joined = "\n".join(executed)
        assert "AUTOINCREMENT" not in joined.upper()
        assert "SERIAL PRIMARY KEY" in joined
        assert "TIMESTAMPTZ" in joined

    def test_migrate_sqlite_to_pg_preserves_serial_ids_and_savepoints(self, tmp_path: Path) -> None:
        from scripts.migrate_sqlite_to_pg import clear_tables, migrate_table

        sqlite_path = tmp_path / "src.db"
        sconn = sqlite3.connect(str(sqlite_path))
        sconn.execute("CREATE TABLE participation_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, active INT)")
        # 制造删行后的非连续主键 (3, 7)
        sconn.execute("INSERT INTO participation_plans (id, name, active) VALUES (3, 'plan-a', 1)")
        sconn.execute("INSERT INTO participation_plans (id, name, active) VALUES (7, 'plan-b', 0)")
        sconn.commit()

        inserted_rows: list[tuple[str, list[Any]]] = []
        savepoint_ops: list[str] = []

        class _FakePgCur:
            rowcount = 1

            def __enter__(self) -> _FakePgCur:
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def execute(self, sql_obj: Any, params: Any = None) -> None:
                s = str(sql_obj)
                if "SAVEPOINT" in s:
                    savepoint_ops.append(s)
                elif s.startswith('INSERT INTO "participation_plans"'):
                    inserted_rows.append((s, list(params)))

            def fetchall(self) -> list[dict[str, str]]:
                if hasattr(self, "_last_meta") and self._last_meta:
                    return [
                        {"column_name": "id", "data_type": "integer"},
                        {"column_name": "name", "data_type": "text"},
                        {"column_name": "active", "data_type": "boolean"},
                    ]
                return []

            def fetchone(self) -> dict[str, Any] | None:
                return {"seq": None}

        class _FakePg:
            def __init__(self) -> None:
                self.deleted: list[str] = []

            def cursor(self) -> Any:
                cur = _FakePgCur()
                orig_exec = cur.execute

                def _exec(sql_obj: Any, params: Any = None) -> None:
                    cur._last_meta = "information_schema.columns" in str(sql_obj)  # type: ignore[attr-defined]
                    orig_exec(sql_obj, params)

                cur.execute = _exec  # type: ignore[method-assign]
                return cur

            def execute(self, sql_obj: Any, params: Any = None) -> Any:
                s = str(sql_obj)
                if "DELETE FROM" in s:
                    self.deleted.append(s)
                m = MagicMock()
                m.fetchall.return_value = []
                return m

            def commit(self) -> None:
                pass

            def rollback(self) -> None:
                pass

        fake_pg = _FakePg()
        stats = migrate_table(sconn, fake_pg, "participation_plans")  # type: ignore[arg-type]
        sconn.close()

        assert stats["inserted"] == 2
        # 原主键 3 与 7 必须完整保留，boolean 列 1/0 转为 True/False
        assert inserted_rows[0][1] == [3, "plan-a", True]
        assert inserted_rows[1][1] == [7, "plan-b", False]
        assert "SAVEPOINT row_sp" in savepoint_ops

        clear_tables(fake_pg, ["users", "sessions", "api_keys"])  # type: ignore[arg-type]
        # 逆序清空：先子表 api_keys / sessions，最后父表 users
        assert len(fake_pg.deleted) == 3
        assert "api_keys" in fake_pg.deleted[0]
        assert "users" in fake_pg.deleted[2]


class TestP02AndP03AuthAndGlobalMutationBoundaries:
    """P0-2 匿名 Token 续期保 ID + P0-3 匿名访客禁止联动篡改全局 projects 表。"""

    def test_anonymous_token_renewal_preserves_valid_hmac_uid_and_rejects_forgery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "auth_renew.db"))
        monkeypatch.setattr(settings, "api_key", "admin-secret-key-for-p02-test-0001")
        monkeypatch.setattr(settings, "auth_token_secret", "hmac-secret-for-p02-renewal-test-0001")
        init_db()

        expired_token = issue_anonymous_token(user_id="anon-abcdef012345", ttl_hours=-1)
        forged_token = "eyJ1c2VyX2lkIjoiYW5vbi0xMTExMTExMTExMTEiLCJyb2xlIjoiYW5vbnltb3VzIiwiZXhwIjoxfQ.bad_sig"

        with TestClient(create_app()) as client:
            # 1. 合法签名虽已过期，续期仍保住原 user_id
            r_renew = client.post("/api/v1/auth/anonymous", json={"previous_token": expired_token})
            assert r_renew.status_code == 200
            assert r_renew.json()["user_id"] == "anon-abcdef012345"

            # 2. 伪造签名无法冒领他人 anon_id，会分配全新 ID
            r_forged = client.post("/api/v1/auth/anonymous", json={"previous_token": forged_token})
            assert r_forged.status_code == 200
            assert r_forged.json()["user_id"] != "anon-111111111111"
            assert r_forged.json()["user_id"].startswith("anon-")

    def test_anonymous_feedback_and_interactions_cannot_mutate_global_projects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        admin_key = "admin-secret-key-for-p03-test-0001"
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "p03.db"))
        monkeypatch.setattr(settings, "api_key", admin_key)
        monkeypatch.setattr(settings, "auth_token_secret", "hmac-secret-for-p03-test-0000001")
        init_db()

        with connection_scope() as conn:
            ProjectRepository(conn).save(
                PipelineState(
                    project=RawProject(id="p-global", name="GlobalProj", sector="L2", stage="testnet"),
                    context=AgentContext(run_id="r1"),
                    score=75,
                    label="FARM",
                    confidence=0.8,
                    reason=["strong signal"],
                )
            )

        with TestClient(create_app()) as client:
            anon_token = client.post("/api/v1/auth/anonymous").json()["access_token"]
            anon_headers = {"Authorization": f"Bearer {anon_token}"}
            admin_headers = {"X-API-Key": admin_key}

            # 匿名提交 wrong_label / airdropped / batch / interaction：个人记录写入成功，但全局项目不变
            assert (
                client.post(
                    "/api/v1/feedback",
                    json={"project_id": "p-global", "signal": "wrong_label", "note": "IGNORE"},
                    headers=anon_headers,
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/feedback/batch",
                    json={"items": [{"project_id": "p-global", "signal": "correct_outcome", "outcome": "airdropped"}]},
                    headers=anon_headers,
                ).status_code
                == 200
            )
            assert (
                client.post(
                    "/api/v1/interactions",
                    json={"project_id": "p-global", "status": "done", "outcome": "airdropped"},
                    headers=anon_headers,
                ).status_code
                == 200
            )

            proj = client.get("/api/v1/projects/p-global", headers=anon_headers).json()["data"]["project"]
            assert proj["label"] == "FARM"
            assert proj["stage"] == "testnet"
            assert proj["veto"] is None

            # 管理员提交 wrong_label 时，允许联动更新全局项目标签
            assert (
                client.post(
                    "/api/v1/feedback",
                    json={"project_id": "p-global", "signal": "wrong_label", "note": "WATCH"},
                    headers=admin_headers,
                ).status_code
                == 200
            )
            proj_admin = client.get("/api/v1/projects/p-global", headers=admin_headers).json()["data"]["project"]
            assert proj_admin["label"] == "WATCH"


class TestP04P05P06AndAdr015:
    """P0-4 旁路机会引擎信号解包、P0-5 发币复查时序覆盖、P0-6 连接池并发与 ADR-015 单调性。"""

    def test_opportunity_engine_unpacks_meta_signals_for_points_project(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "opp_signals.db"))
        init_db()

        with connection_scope() as conn:
            repo = ProjectRepository(conn)
            repo.save(
                PipelineState(
                    project=RawProject(
                        id="points-tier1",
                        name="Tier1PointsL2",
                        sector="L2",
                        stage="mainnet",
                        has_points_program=True,
                        explicit_points_program=True,
                        funding_total_usd=30_000_000.0,
                        funding_tier="tier1",
                        funding_lead_investors=["Paradigm"],
                        tvl_usd=120_000_000.0,
                    ),
                    context=AgentContext(run_id="r-opp"),
                    score=82,
                    label="FARM",
                    confidence=0.85,
                    reason=[],
                )
            )
            repo.update_meta_signals("points-tier1", {"site_alive": False, "github_recent_push_days": 75})

        with OpportunityService() as svc:
            assessment = svc.evaluate("points-tier1")

        # 绝不能因顶层列无融资/TVL 而被误判成 UNBACKED_POINTS_MACHINE (unviable / LOW_RUNWAY_RISK)
        assert assessment.viability_tier == "viable"
        assert assessment.viability_advisory is not None
        assert "LOW_RUNWAY_RISK" not in assessment.ignore_reason_codes
        # meta.signals 中的官网离线与停更信号应正确传入 exit_advisory
        assert assessment.exit_advisory is not None
        assert assessment.exit_advisory["active"] is True
        assert set(assessment.exit_advisory["reasons"]) >= {"SITE_OFFLINE", "DEV_INACTIVE"}

    def test_launch_review_hides_pre_tge_project_after_newer_post_tge_raw_row(self, tmp_path: Path) -> None:
        raw_conn = sqlite3.connect(str(tmp_path / "launch_tge.db"))
        raw_conn.row_factory = sqlite3.Row
        init_db(raw_conn)
        try:
            # Day 1：项目在发币前评分入库，meta.signals 带 no_token_yet=True
            ProjectRepository(raw_conn).save(
                PipelineState(
                    project=RawProject(
                        id="later-tge",
                        name="LaterTGE",
                        sector="DeFi",
                        stage="testnet",
                        no_token_yet=True,
                    ),
                    context=AgentContext(run_id="day1"),
                    score=72,
                    label="FARM",
                    confidence=0.75,
                    reason=[],
                )
            )
            raw_conn.execute(
                "UPDATE projects SET updated_at = ? WHERE id = 'later-tge'",
                ("2026-08-01T00:00:00+00:00",),
            )
            # Day 60：项目发币且无后续路径，新采集行晚于 projects.updated_at
            raw_conn.execute(
                """
                INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, processed, project_id)
                VALUES ('r-tge', 'rootdata', 'latertge::DeFi', ?, '2026-10-01T00:00:00+00:00', 0, 'later-tge')
                """,
                (json.dumps({"name": "LaterTGE", "no_token_yet": False, "token_symbol": "LTG"}),),
            )
            raw_conn.commit()

            stats = run_launch_review(raw_conn)
            hidden = raw_conn.execute("SELECT hidden_reason FROM projects WHERE id = 'later-tge'").fetchone()[
                "hidden_reason"
            ]
            assert stats["hidden"] == 1
            assert hidden == HIDDEN_REASON_ALREADY_LAUNCHED
        finally:
            raw_conn.close()

    def test_sqlite_pool_thread_safety_under_concurrent_checkout(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "pool_race.db"))
        monkeypatch.setattr(settings, "app_env", "development")
        init_db()

        errors: list[Exception] = []

        def _worker() -> None:
            try:
                for _ in range(25):
                    with connection_scope() as conn:
                        conn.execute("SELECT 1").fetchone()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_main_on_collection_serializes_concurrent_persistence_on_shared_conn(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.main as main_module
        from app.collectors.base import CollectorResult

        monkeypatch.setattr(main_module.settings, "app_env", "development")
        monkeypatch.setattr(main_module.settings, "collection_auto_run_enabled", False)
        monkeypatch.setattr(main_module, "init_db", lambda: None)

        active = {"current": 0, "max_seen": 0}
        state_lock = threading.Lock()
        captured_cb: dict[str, Any] = {}

        class _GuardedRepo:
            def __init__(self, _conn: Any = None) -> None:
                pass

            def persist_collection_result(self, *args: Any, **kwargs: Any) -> None:
                with state_lock:
                    active["current"] += 1
                    active["max_seen"] = max(active["max_seen"], active["current"])
                time.sleep(0.02)
                with state_lock:
                    active["current"] -= 1

        class _CaptureScheduler:
            def __init__(self, _reg: Any, on_collection: Any) -> None:
                captured_cb["fn"] = on_collection

            def start(self) -> None:
                pass

            def shutdown(self, *, wait: bool) -> None:
                pass

        dummy_conn = MagicMock()
        monkeypatch.setattr(main_module, "get_connection", lambda: dummy_conn)
        monkeypatch.setattr(main_module, "CollectionRepository", _GuardedRepo)
        monkeypatch.setattr(main_module, "UnifiedScheduler", _CaptureScheduler)

        with TestClient(main_module.create_app()):
            cb = captured_cb["fn"]

            async def _burst() -> None:
                await asyncio.gather(
                    *(cb(f"src-{i}", CollectorResult(source_id=f"src-{i}", status="success")) for i in range(6))
                )

            asyncio.run(_burst())

        assert active["max_seen"] == 1

    def test_adr015_watch_already_launched_downgrades_monotonically_to_ignore(self) -> None:
        launched_watch = RawProject(
            id="launched-watch",
            name="LaunchedWatch",
            sector="DeFi",
            no_token_yet=False,
            token_launch_confirmed=True,
            has_testnet=False,
            has_points_program=False,
            has_task_portal=False,
            explicit_airdrop_mention=False,
        )
        decision = apply_eligibility_gate(launched_watch, "WATCH")
        assert decision.label == "IGNORE"
        assert decision.veto == VETO_ALREADY_LAUNCHED
