# ──────────────────────────────────────────────
# pytest 测试配置 — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 全局 Fixture：数据库、测试客户端、示例项目、Mock fetcher
# ──────────────────────────────────────────────

import json
import sqlite3
import pytest
from typing import Generator
from pathlib import Path

# ── 路径 ─────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ── Database Fixture ─────────────────────────
@pytest.fixture
def db() -> Generator[sqlite3.Connection, None, None]:
    """提供内存 SQLite 数据库，测试间自动清理"""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    # 创建测试表（完整 DDL 见 DATABASE_DDL.md）
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            url             TEXT,
            sector          TEXT,
            stage           TEXT,
            score           INTEGER,
            label           TEXT,
            recommendation  TEXT,
            confidence      REAL,
            weight_version  TEXT,
            reason          TEXT,
            narrative_json  TEXT,
            team_json       TEXT,
            risk_json       TEXT,
            tokenomics_json TEXT,
            raw_signals     TEXT,
            meta            TEXT,
            source          TEXT,
            raw_signals_hash TEXT,
            fetched_at      TIMESTAMP,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id      TEXT NOT NULL,
            project_id  TEXT,
            agent_name  TEXT,
            input       TEXT,
            output      TEXT,
            error       TEXT,
            duration_ms INTEGER,
            timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        -- 索引
        CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(score);
        CREATE INDEX IF NOT EXISTS idx_projects_label ON projects(label);
        CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id);
    """)

    yield conn
    conn.close()


# ── Sample Project Fixture ───────────────────
@pytest.fixture
def sample_project():
    """标准测试项目 — LayerX 示例"""
    return {
        "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
        "name": "LayerX",
        "url": "https://layerx.xyz",
        "sector": "L2",
        "stage": "testnet",
        "raw_signals": {
            "has_points": True,
            "airdrop_hint": True,
            "sources": ["seed"]
        },
        "heat_score": 0.82,
        "narrative_stage": "growth",
        "team_score": 0.72,
        "team_flags": [],
        "token_risk": 0.35,
        "vc_share": 0.25,
        "team_share": 0.20,
        "unlock_pressure": "medium",
    }


@pytest.fixture
def sample_project_empty():
    """最低信号测试项目"""
    return {
        "id": "e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b",
        "name": "EmptyProject",
        "url": None,
        "sector": "Unknown",
        "stage": "ideation",
        "raw_signals": {},
    }


# ── Test Client Fixture ──────────────────────
@pytest.fixture
def app_client(db):
    """FastAPI 测试客户端（需在实现后取消注释）"""
    # from app.main import create_app
    # app = create_app(db_override=db)
    # from fastapi.testclient import TestClient
    # return TestClient(app)
    pytest.skip("App not yet implemented")


# ── Settings Fixture ─────────────────────────
@pytest.fixture
def default_settings():
    """默认配置"""
    return {
        "port": 8000,
        "debug": False,
        "db_path": ":memory:",
        "api_key": "",
        "weight_airdrop_signal": 0.20,
        "weight_narrative_timing": 0.20,
        "weight_team_reputation": 0.15,
        "weight_risk": 0.15,
        "weight_tokenomics": 0.15,
        "weight_competition": 0.15,
        "max_concurrent_projects": 10,
        "llm_semaphore_size": 5,
        "openai_api_key": "",
        "llm_model": "gpt-4o-mini",
        "daily_budget_usd": 1.0,
    }


# ── Mock Helpers ─────────────────────────────
@pytest.fixture
def mock_fetcher_response():
    """模拟 fetcher 返回"""
    return {
        "status": 200,
        "data": {"protocols": [], "new": []},
        "cached": False,
    }


# ── Golden Test Data ─────────────────────────
@pytest.fixture
def golden_test_cases():
    """golden 回归测试用例"""
    return [
        {
            "name": "LayerX",
            "sector": "L2",
            "stage": "testnet",
            "expected_score": 67,
            "expected_label": "WATCH",
            "reason_contains": ["strong airdrop signal", "early narrative"],
        },
    ]
