"""E4: project_history 写入测试（§6.9.12 / §6.11）.

验证 save() 事务内同时写 projects + project_history：
1. 一次 run 后 project_history 有对应快照行
2. 快照包含完整评分状态（score/label/stage/run_id/weight_version/snapshot JSON）
3. 多次 save 产生多条历史记录
4. 事务回滚时两表一致（projects 和 project_history 同时撤销）

Reference:
- docs/V2_TASKS.md E4
- backend/app/repository.py save()
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.models import NarrativeResult, RiskResult, TeamResult, TokenomicsResult
from app.repository import ProjectRepository


@pytest.fixture
def db_conn():
    """In-memory SQLite database with schema."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_state():
    """Sample pipeline state with full analysis results."""
    project = RawProject(
        id="hist-test-001",
        name="History Test Project",
        url="https://test.xyz",
        sector="L2",
        stage="testnet",
        source="test",
    )
    context = AgentContext(run_id="run-e4-001", enable_llm=False)
    state = PipelineState(project=project, context=context)

    state.narrative = NarrativeResult(sector="L2", stage="growth", heat_score=0.9, timing="early")
    state.team = TeamResult(team_score=0.8, team_flags=["tier-1 backed"], team_type="semi_anon")
    state.risk = RiskResult(token_risk=0.3, risk_flags=[], unlock_pressure="medium")
    state.tokenomics = TokenomicsResult(vc_share=0.3, team_share=0.25, unlock_penalty=0.35)
    state.score = 85
    state.label = "FARM"
    state.confidence = 0.95
    state.reason = ["strong signal", "early timing"]
    state.weight_version = "v1.2-default"
    state.sub_scores = {"airdrop_signal": 0.9, "narrative": 0.8}

    return state


class TestProjectHistoryWrite:
    """save() 事务内写入 project_history 快照行。"""

    def test_history_row_created_after_save(self, db_conn, sample_state):
        """一次 save 后 project_history 有对应快照行。"""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        rows = db_conn.execute(
            "SELECT * FROM project_history WHERE project_id = ?",
            (sample_state.project.id,),
        ).fetchall()

        assert len(rows) == 1
        row = rows[0]
        assert row["project_id"] == "hist-test-001"
        assert row["run_id"] == "run-e4-001"
        assert row["score"] == 85
        assert row["label"] == "FARM"
        assert row["stage"] == "testnet"
        assert row["weight_version"] == "v1.2-default"

    def test_history_snapshot_contains_full_state(self, db_conn, sample_state):
        """快照 JSON 包含完整评分状态。"""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        row = db_conn.execute(
            "SELECT snapshot FROM project_history WHERE project_id = ?",
            (sample_state.project.id,),
        ).fetchone()

        snapshot = json.loads(row["snapshot"])
        assert snapshot["project_name"] == "History Test Project"
        assert snapshot["sector"] == "L2"
        assert snapshot["source"] == "test"
        assert snapshot["confidence"] == 0.95
        assert snapshot["reason"] == ["strong signal", "early timing"]
        assert snapshot["narrative"]["heat_score"] == 0.9
        assert snapshot["team"]["team_score"] == 0.8
        assert snapshot["risk"]["token_risk"] == 0.3
        assert snapshot["tokenomics"]["vc_share"] == 0.3
        assert snapshot["sub_scores"]["airdrop_signal"] == 0.9
        assert snapshot["meta"] is not None

    def test_multiple_saves_create_multiple_history_rows(self, db_conn, sample_state):
        """多次 save 产生多条历史记录。"""
        repo = ProjectRepository(db_conn)

        # First save
        repo.save(sample_state)

        # Update and save again
        sample_state.score = 90
        sample_state.label = "WATCH"
        sample_state.context.run_id = "run-e4-002"
        repo.save(sample_state)

        rows = db_conn.execute(
            "SELECT * FROM project_history WHERE project_id = ? ORDER BY id ASC",
            (sample_state.project.id,),
        ).fetchall()

        assert len(rows) == 2
        assert rows[0]["run_id"] == "run-e4-001"
        assert rows[0]["score"] == 85
        assert rows[1]["run_id"] == "run-e4-002"
        assert rows[1]["score"] == 90

    def test_transaction_rollback_no_history(self, db_conn, sample_state):
        """事务回滚时 project_history 不留残余行。

        模拟 save() 在 commit 前抛异常 → projects 和 project_history 同时撤销。
        做法：临时 DROP project_history 表，使 save() 内的 INSERT 失败，
        验证回滚后 projects 表也没有残留行。
        """
        repo = ProjectRepository(db_conn)

        # Drop project_history table to force INSERT failure inside save()
        db_conn.execute("DROP TABLE project_history")

        # save() should raise due to missing project_history table
        with pytest.raises(sqlite3.OperationalError):
            repo.save(sample_state)

        # Neither projects nor project_history should have the row
        # (project_history table doesn't exist, but projects should be rolled back)
        proj = db_conn.execute("SELECT * FROM projects WHERE id = ?", (sample_state.project.id,)).fetchone()
        assert proj is None, "projects row should not exist after rollback"

        # Recreate the table for other tests that might share the fixture
        db_conn.execute("""
            CREATE TABLE IF NOT EXISTS project_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      TEXT NOT NULL,
                run_id          TEXT NOT NULL,
                score           INTEGER,
                label           TEXT,
                stage           TEXT,
                weight_version  TEXT,
                snapshot        TEXT NOT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

    def test_history_query_by_run(self, db_conn, sample_state):
        """ProjectHistoryRepository.query_by_run 返回正确结果。"""
        from app.repositories.v2 import ProjectHistoryRepository

        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        hist_repo = ProjectHistoryRepository(db_conn)
        rows = hist_repo.query_by_run("run-e4-001")
        assert len(rows) == 1
        assert rows[0]["project_id"] == "hist-test-001"

    def test_history_query_by_project(self, db_conn, sample_state):
        """ProjectHistoryRepository.query_by_project 返回按时间倒序的结果。"""
        from app.repositories.v2 import ProjectHistoryRepository

        repo = ProjectRepository(db_conn)

        # Save multiple times with different run_ids
        for i in range(3):
            sample_state.context.run_id = f"run-e4-{i:03d}"
            sample_state.score = 80 + i
            repo.save(sample_state)

        hist_repo = ProjectHistoryRepository(db_conn)
        rows = hist_repo.query_by_project("hist-test-001")
        assert len(rows) == 3
        # Most recent first (ORDER BY created_at DESC, id DESC)
        assert rows[0]["score"] == 82
        assert rows[2]["score"] == 80

    def test_history_weight_version_null_when_unset(self, db_conn, sample_state):
        """weight_version 未设时存 NULL。"""
        repo = ProjectRepository(db_conn)
        sample_state.weight_version = None
        repo.save(sample_state)

        row = db_conn.execute(
            "SELECT weight_version FROM project_history WHERE project_id = ?",
            (sample_state.project.id,),
        ).fetchone()
        assert row["weight_version"] is None

    def test_history_run_id_from_context(self, db_conn, sample_state):
        """run_id 从 state.context.run_id 正确提取。"""
        repo = ProjectRepository(db_conn)
        sample_state.context.run_id = "custom-run-id-999"
        repo.save(sample_state)

        row = db_conn.execute(
            "SELECT run_id FROM project_history WHERE project_id = ?",
            (sample_state.project.id,),
        ).fetchone()
        assert row["run_id"] == "custom-run-id-999"
