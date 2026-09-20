"""API integration tests for Memory system endpoints (Roadmap §24.3 / W12-02)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.repositories.v2 import ProjectHistoryRepository


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_project_timeline_404_when_not_found(client):
    resp = client.get("/api/v1/projects/nonexistent-xyz/timeline")
    assert resp.status_code == 404
    data = resp.json()
    assert data["ok"] is False
    assert data["error"]["code"] == "NOT_FOUND"


def test_project_timeline_success(client):
    from app.db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (id, name, sector, stage, score, label, confidence, created_at)
            VALUES ('mem-proj-api-1', 'Memory API Proj', 'L2', 'mainnet', 88, 'FARM', 0.9, '2026-08-01 12:00:00')
            """
        )
        repo = ProjectHistoryRepository(conn)
        repo.insert(
            project_id="mem-proj-api-1",
            run_id="run-api-1",
            score=70,
            label="WATCH",
            stage="testnet",
            snapshot="{}",
        )
        repo.insert(
            project_id="mem-proj-api-1",
            run_id="run-api-2",
            score=88,
            label="FARM",
            stage="mainnet",
            snapshot="{}",
        )
        conn.commit()

    resp = client.get("/api/v1/projects/mem-proj-api-1/timeline")
    assert resp.status_code == 200
    res = resp.json()
    assert res["ok"] is True
    data = res["data"]
    assert data["project_id"] == "mem-proj-api-1"
    assert data["project_name"] == "Memory API Proj"
    assert data["snapshot_count"] >= 2
    assert data["score_trend"] == "rising"
    assert "testnet" in data["stage_progression"]
    assert "mainnet" in data["stage_progression"]
    assert len(data["timeline"]) >= 2


def test_user_profile_get_and_clear(client):
    uid = "test-api-user-99"

    resp = client.get(f"/api/v1/user-profile?user_id={uid}")
    assert resp.status_code == 200
    res = resp.json()
    assert res["ok"] is True
    data = res["data"]
    assert data["user_id"] == uid
    assert isinstance(data["sector_affinity"], dict)
    assert data["risk_tolerance"] in ("conservative", "moderate", "aggressive")
    assert not data["is_cleared"]

    del_resp = client.delete(f"/api/v1/user-profile?user_id={uid}")
    assert del_resp.status_code == 200
    del_res = del_resp.json()
    assert del_res["ok"] is True
    assert del_res["data"]["is_cleared"] is True


def test_projects_list_with_personalized(client):
    from app.db import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (id, name, sector, stage, score, label, confidence)
            VALUES ('mem-pers-1', 'Personalized Project 1', 'AI', 'testnet', 80, 'FARM', 0.9)
            """
        )
        conn.commit()

    resp = client.get("/api/v1/projects?personalized=true&user_id=default")
    assert resp.status_code == 200
    res = resp.json()
    assert res["ok"] is True
    assert "projects" in res["data"]
    assert len(res["data"]["projects"]) >= 1
