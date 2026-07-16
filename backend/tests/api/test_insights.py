"""Tests for the insights aggregation endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """使用临时数据库创建隔离的 TestClient。"""
    db_path = tmp_path / "insights_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    app = create_app()
    return TestClient(app)


@pytest.fixture
def _seed_projects(client):
    """通过 /run 端点创建测试项目。"""
    projects = [
        {
            "name": "Insights L2 Alpha",
            "sector": "L2",
            "stage": "testnet",
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "recent_funding": True,
        },
        {
            "name": "Insights DeFi Risk",
            "sector": "DeFi",
            "stage": "ideation",
            "has_testnet": False,
            "has_points_program": False,
            "no_token_yet": True,
            "recent_funding": False,
        },
        {
            "name": "Insights Gaming Watch",
            "sector": "Gaming",
            "stage": "mainnet",
            "has_testnet": True,
            "has_points_program": False,
            "no_token_yet": True,
            "recent_funding": True,
        },
    ]
    response = client.post("/api/v1/run", json={"projects": projects, "enable_llm": False})
    assert response.status_code == 200
    return response.json()["data"]


class TestInsightsEndpoints:
    def test_insights_empty(self, client) -> None:
        """无项目时返回空聚合。"""
        response = client.get("/api/v1/insights")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["total_projects"] == 0
        assert data["label_counts"] == {}
        assert data["sector_counts"] == {}
        assert data["hottest_narratives"] == []
        assert data["risky_teams"] == []

    def test_insights_aggregation(self, client, _seed_projects) -> None:
        """有项目时正确聚合分布、叙事热度与团队风险。"""
        response = client.get("/api/v1/insights")
        assert response.status_code == 200
        data = response.json()["data"]

        assert data["total_projects"] == 3
        assert "FARM" in data["label_counts"]
        assert sum(data["label_counts"].values()) == 3
        assert set(data["sector_counts"].keys()) >= {"L2", "DeFi", "Gaming"}

        # Hottest narratives should include L2 (strong signals => high heat)
        sectors = [item["sector"] for item in data["hottest_narratives"]]
        assert "L2" in sectors
        hottest = data["hottest_narratives"][0]
        assert "avg_heat_score" in hottest
        assert "trend" in hottest
        assert hottest["project_count"] >= 1

        # DeFi ideation with anonymous team should surface as risky
        risky_names = [item["name"] for item in data["risky_teams"]]
        assert "Insights DeFi Risk" in risky_names
