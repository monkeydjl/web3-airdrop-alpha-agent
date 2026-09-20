"""Tests for Project Evolution Memory service (Roadmap §24.3 / W12-02)."""

import sqlite3

import pytest

from app.db import init_db
from app.repositories.v2 import ProjectHistoryRepository
from app.services.project_memory import ProjectEvolutionService


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def test_timeline_nonexistent_project(memory_db):
    svc = ProjectEvolutionService(conn=memory_db)
    result = svc.get_project_timeline("nonexistent-xyz")
    assert result is None


def test_timeline_fallback_to_project_row(memory_db):
    memory_db.execute(
        """
        INSERT INTO projects (id, name, sector, stage, score, label, confidence, created_at)
        VALUES ('proj-fallback-1', 'Fallback Project', 'L2', 'testnet', 75, 'WATCH', 0.9, '2026-08-01 10:00:00')
        """
    )
    memory_db.commit()

    svc = ProjectEvolutionService(conn=memory_db)
    evolution = svc.get_project_timeline("proj-fallback-1")

    assert evolution is not None
    assert evolution.project_id == "proj-fallback-1"
    assert evolution.project_name == "Fallback Project"
    assert evolution.snapshot_count == 1
    assert evolution.score_trend == "insufficient_data"
    assert evolution.score_volatility == 0.0
    assert evolution.stage_progression == ["testnet"]
    assert len(evolution.timeline) == 1
    assert evolution.timeline[0]["score"] == 75
    assert evolution.timeline[0]["label"] == "WATCH"
    assert "Fallback Project" in evolution.llm_context_summary


def test_timeline_multi_snapshots_rising_trend(memory_db):
    memory_db.execute(
        """
        INSERT INTO projects (id, name, sector, stage, score, label, confidence)
        VALUES ('proj-multi-1', 'Evolving L2', 'L2', 'mainnet', 85, 'FARM', 0.95)
        """
    )
    repo = ProjectHistoryRepository(memory_db)

    # 3 snapshots: 65 (testnet) -> 75 (testnet) -> 85 (mainnet)
    repo.insert(
        project_id="proj-multi-1",
        run_id="run-1",
        score=65,
        label="WATCH",
        stage="testnet",
        snapshot="{}",
    )
    repo.insert(
        project_id="proj-multi-1",
        run_id="run-2",
        score=75,
        label="WATCH",
        stage="testnet",
        snapshot="{}",
    )
    repo.insert(
        project_id="proj-multi-1",
        run_id="run-3",
        score=85,
        label="FARM",
        stage="mainnet",
        snapshot="{}",
    )

    svc = ProjectEvolutionService(conn=memory_db)
    evolution = svc.get_project_timeline("proj-multi-1")

    assert evolution is not None
    assert evolution.snapshot_count == 3
    assert evolution.score_trend == "rising"
    assert evolution.score_volatility > 0.0
    assert evolution.stage_progression == ["testnet", "mainnet"]
    assert len(evolution.stage_transitions) == 1
    assert evolution.stage_transitions[0]["from_stage"] == "testnet"
    assert evolution.stage_transitions[0]["to_stage"] == "mainnet"
    assert evolution.label_history == ["WATCH", "FARM"]
    assert len(evolution.timeline) == 3
    assert evolution.timeline[0]["score"] == 65
    assert evolution.timeline[1]["diff_from_previous_score"] == 10
    assert evolution.timeline[2]["diff_from_previous_score"] == 10
    assert "上升" in evolution.llm_context_summary


def test_timeline_falling_trend(memory_db):
    memory_db.execute(
        """
        INSERT INTO projects (id, name, sector, stage, score, label, confidence)
        VALUES ('proj-falling-1', 'Declining DEX', 'DeFi', 'mainnet', 50, 'IGNORE', 0.8)
        """
    )
    repo = ProjectHistoryRepository(memory_db)
    repo.insert(project_id="proj-falling-1", run_id="run-1", score=80, label="FARM", stage="mainnet", snapshot="{}")
    repo.insert(project_id="proj-falling-1", run_id="run-2", score=50, label="IGNORE", stage="mainnet", snapshot="{}")

    svc = ProjectEvolutionService(conn=memory_db)
    evolution = svc.get_project_timeline("proj-falling-1")

    assert evolution is not None
    assert evolution.score_trend == "falling"
    assert evolution.label_history == ["FARM", "IGNORE"]
    assert evolution.timeline[1]["diff_from_previous_score"] == -30
    assert "下行" in evolution.llm_context_summary


def test_format_evolution_context(memory_db):
    memory_db.execute(
        """
        INSERT INTO projects (id, name, sector, stage, score, label, confidence)
        VALUES ('proj-ctx-1', 'Context Test', 'AI', 'testnet', 70, 'WATCH', 0.85)
        """
    )
    svc = ProjectEvolutionService(conn=memory_db)
    ctx = svc.format_evolution_context("proj-ctx-1")
    assert "Context Test" in ctx
    assert "WATCH" in ctx

    empty_ctx = svc.format_evolution_context("nonexistent")
    assert empty_ctx == ""
