"""Tests for Single Project Evaluation and Alpha Dossier Generation.

Endpoints:
- POST /api/v1/projects/{project_id}/evaluate
- GET /api/v1/projects/{project_id}/dossier
"""

import json
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app
from app.repository import ProjectRepository


@pytest.fixture
def client(monkeypatch, tmp_path):
    """Test client fixture with isolated test database."""
    test_db = str(tmp_path / "test_eval_dossier.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    init_db()

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO projects (
                id, name, sector, stage, score, label, confidence, source, meta
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "eval-test-001",
                "Alpha Testnet Protocol",
                "infra",
                "testnet",
                55,
                "WATCH",
                0.75,
                "defillama",
                json.dumps({
                    "signals": {
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "total_raised_usd": 12000000,
                        "monthly_burn_rate_usd": 250000,
                        "farming_days": 180,
                        "gas_spent_usd": 45,
                        "tvl_deposited_usd": 500,
                    },
                    "funding_note": "$12M Series A led by Paradigm",
                }),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app()
    return TestClient(app)


def test_evaluate_project_success(client):
    """Test POST /api/v1/projects/{id}/evaluate updates score and records history."""
    response = client.post("/api/v1/projects/eval-test-001/evaluate")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "data" in data
    assert "project" in data["data"]

    project = data["data"]["project"]
    assert project["id"] == "eval-test-001"
    assert project["name"] == "Alpha Testnet Protocol"
    assert isinstance(project["score"], int)
    assert project["label"] in ("FARM", "WATCH", "IGNORE")

    # Verify project_history snapshot was written
    conn = get_connection()
    try:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM project_history WHERE project_id = ?",
            ("eval-test-001",),
        )
        history_count = cursor.fetchone()[0]
        assert history_count >= 1
    finally:
        conn.close()


def test_evaluate_project_not_found(client):
    """Test POST /api/v1/projects/{id}/evaluate returns 404 for missing project."""
    response = client.post("/api/v1/projects/non-existent-proj/evaluate")
    assert response.status_code == 404
    data = response.json()
    error_code = data.get("error", {}).get("code") or data.get("detail", {}).get("code")
    assert error_code == "NOT_FOUND"


def test_get_project_dossier_success(client):
    """Test GET /api/v1/projects/{id}/dossier returns complete Alpha Dossier."""
    response = client.get("/api/v1/projects/eval-test-001/dossier")
    assert response.status_code == 200

    data = response.json()
    assert data["ok"] is True
    assert "data" in data

    dossier = data["data"]
    assert dossier["project_id"] == "eval-test-001"
    assert dossier["project_name"] == "Alpha Testnet Protocol"
    assert "markdown" in dossier
    assert "summary" in dossier

    md = dossier["markdown"]
    assert "Alpha 深度投研研报: Alpha Testnet Protocol" in md
    assert "项目基本面与叙事定位" in md
    assert "机构背书与跑道存活率评估" in md
    assert "防 PUA 疲劳指数与资本摩擦分析" in md
    assert "多源免费情报共识印证" in md
    assert "多钱包防女巫参与指南" in md
    assert "保姆级交互清单与水龙头指引" in md

    summary = dossier["summary"]
    assert "fatigue_index" in summary
    assert "friction_tier" in summary
    assert "runway_months" in summary
    assert "consensus_signals" in summary
    assert "multi_wallet_tier" in summary


def test_get_project_dossier_not_found(client):
    """Test GET /api/v1/projects/{id}/dossier returns 404 for missing project."""
    response = client.get("/api/v1/projects/non-existent-proj/dossier")
    assert response.status_code == 404
    data = response.json()
    error_code = data.get("error", {}).get("code") or data.get("detail", {}).get("code")
    assert error_code == "NOT_FOUND"
