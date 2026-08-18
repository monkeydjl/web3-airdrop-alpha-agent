"""Tests for Watchlist API endpoints.

Reference:
- backend/app/routers/v1/watchlist.py
- ADR-008-user-system.md
"""

import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_watchlist():
    """每次测试前清理 watchlist 表。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM watchlist")
        conn.commit()


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_project():
    """插入一条测试项目并返回 project_id。"""
    pid = "test-watchlist-proj-001"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (id, name, sector, stage, score, label, confidence)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, "TestWatchProject", "DeFi", "testnet", 82, "FARM", 0.9),
        )
        conn.commit()
    return pid


class TestAddToWatchlist:
    def test_add_success(self, client, sample_project):
        """成功添加项目到 watchlist。"""
        resp = client.post(
            f"/api/v1/watchlist/{sample_project}",
            json={"note": "Watching this one"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["project_id"] == sample_project
        assert data["action"] == "added"

    def test_add_duplicate_returns_409(self, client, sample_project):
        """重复添加返回 409。"""
        client.post(f"/api/v1/watchlist/{sample_project}", json={})
        resp = client.post(f"/api/v1/watchlist/{sample_project}", json={})
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ALREADY_WATCHED"

    def test_add_nonexistent_project_returns_404(self, client):
        """项目不存在返回 404。"""
        resp = client.post(
            "/api/v1/watchlist/nonexistent-xxx",
            json={},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_FOUND"


class TestRemoveFromWatchlist:
    def test_remove_success(self, client, sample_project):
        """成功移除。"""
        client.post(f"/api/v1/watchlist/{sample_project}", json={})
        resp = client.delete(f"/api/v1/watchlist/{sample_project}")
        assert resp.status_code == 200
        assert resp.json()["data"]["action"] == "removed"

    def test_remove_not_in_list_returns_404(self, client, sample_project):
        """不在 watchlist 中返回 404。"""
        resp = client.delete(f"/api/v1/watchlist/{sample_project}")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "NOT_IN_WATCHLIST"


class TestListWatchlist:
    def test_list_empty(self, client):
        """空 watchlist 返回空列表。"""
        resp = client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0

    def test_list_with_project(self, client, sample_project):
        """列出 watchlist 项目，包含评分信息。"""
        client.post(
            f"/api/v1/watchlist/{sample_project}",
            json={"note": "test note"},
        )
        resp = client.get("/api/v1/watchlist")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        item = data["items"][0]
        assert item["project_id"] == sample_project
        assert item["name"] == "TestWatchProject"
        assert item["score"] == 82
        assert item["label"] == "FARM"
        assert item["note"] == "test note"

    def test_list_pagination(self, client, sample_project):
        """分页查询。"""
        # 插入额外项目
        with get_connection() as conn:
            for i in range(5):
                pid = f"test-watchlist-page-{i:03d}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO projects (id, name, sector, stage, score, label, confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (pid, f"PageProj{i}", "DeFi", "mainnet", 60 + i, "WATCH", 0.7),
                )
                conn.execute(
                    "INSERT INTO watchlist (project_id, user_id) VALUES (?, ?)",
                    (pid, "default"),
                )
            conn.commit()

        resp = client.get("/api/v1/watchlist?page=1&page_size=3")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["items"]) == 3
        assert data["total"] >= 5
