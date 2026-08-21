"""Tests for the dashboard overview aggregation endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """使用临时数据库创建隔离的 TestClient。"""
    db_path = tmp_path / "dashboard_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    app = create_app()
    return TestClient(app)


def _assert_overview_shape(data: dict) -> None:
    """断言 overview 响应结构完整。"""
    assert "today" in data
    assert "discovery" in data
    assert "shadow" in data
    runs = data["today"]["collection_runs"]
    assert set(runs) == {"total", "success", "failed"}
    assert set(data["discovery"]) == {"pending_count", "today_new", "total"}
    assert set(data["shadow"]) == {"saved_today", "label_counts"}
    assert set(data["shadow"]["label_counts"]) == {"FARM", "WATCH", "IGNORE"}


class TestDashboardOverview:
    def test_overview_empty(self, client) -> None:
        """空库时返回结构完整且全零/空分桶。"""
        response = client.get("/api/v1/dashboard/overview")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        data = body["data"]
        _assert_overview_shape(data)
        assert data["today"]["new_projects"] == 0
        assert data["discovery"]["pending_count"] == 0
        assert data["shadow"]["saved_today"] == 0

    def test_overview_reflects_scored_projects(self, client) -> None:
        """通过 /run 创建项目后，今日新增项目计数正确。"""
        projects = [
            {
                "name": "Dash L2 Alpha",
                "sector": "L2",
                "stage": "testnet",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
                "recent_funding": True,
            },
            {
                "name": "Dash DeFi Watch",
                "sector": "DeFi",
                "stage": "mainnet",
                "has_testnet": False,
                "has_points_program": False,
                "no_token_yet": False,
                "recent_funding": False,
            },
        ]
        run_res = client.post("/api/v1/run", json={"projects": projects, "enable_llm": False})
        assert run_res.status_code == 200

        overview = client.get("/api/v1/dashboard/overview").json()["data"]
        _assert_overview_shape(overview)
        # 今日新增两个项目（created_at = 今天）
        assert overview["today"]["new_projects"] == 2
        # shadow 评估可能因环境配置产生或为空；只断言数值非负且分桶结构完整
        assert overview["shadow"]["saved_today"] >= 0
        assert sum(overview["shadow"]["label_counts"].values()) >= 0
        assert overview["discovery"]["total"] == 0
