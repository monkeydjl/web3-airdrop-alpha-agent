"""Tests for collection endpoints and auto-run flow."""

from __future__ import annotations

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import settings
from app.db import init_db
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，每个测试使用独立数据库。"""
    db_path = tmp_path / "test.db"
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


class TestCollectionsEndpoints:
    @respx.mock
    def test_trigger_defillama_collection(self, client: TestClient) -> None:
        """手动触发 DefiLlama 采集。"""
        protocols = [
            {
                "name": "Alpha Protocol",
                "slug": "alpha",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "Lending",
                "chains": ["Ethereum"],
                "url": "https://alpha.example.com",
                "twitter": "@alpha",
                "github": "alpha/repo",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

        response = client.post("/api/v1/collections/defillama/trigger")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["source_id"] == "defillama"
        assert data["items_collected"] == 1
        assert data["items_new"] == 1

    def test_list_collection_sources(self, client: TestClient) -> None:
        """列出采集源。"""
        response = client.get("/api/v1/collections/sources")

        assert response.status_code == 200
        sources = response.json()["data"]["sources"]
        assert any(s["source_id"] == "defillama" for s in sources)

    def test_list_discoveries_empty(self, client: TestClient) -> None:
        """空发现列表。"""
        response = client.get("/api/v1/discoveries")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0


class TestRunAutoPath:
    @respx.mock
    def test_run_without_projects_uses_raw_projects(self, client: TestClient) -> None:
        """不提供 projects 时，自动从 raw_projects 表读取。"""
        # 先触发采集
        protocols = [
            {
                "name": "Auto Project",
                "slug": "auto-project",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "L2",
                "chains": ["Ethereum", "Arbitrum"],
                "url": "https://auto.example.com",
                "twitter": "@auto",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        trigger = client.post("/api/v1/collections/defillama/trigger")
        assert trigger.status_code == 200

        # 再运行 pipeline（不带 projects）
        response = client.post("/api/v1/run", json={})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_count"] >= 1
        assert data["status"] in ("completed", "partial")

    def test_run_without_projects_empty_db(self, client: TestClient) -> None:
        """数据库为空且不提供 projects 时返回空结果。"""
        response = client.post("/api/v1/run", json={})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_count"] == 0

    @respx.mock
    def test_run_marks_raw_projects_processed(self, client: TestClient) -> None:
        """评分成功后 raw_projects 应标记 processed。"""
        protocols = [
            {
                "name": "MarkMe",
                "slug": "mark-me",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "L2",
                "chains": ["Ethereum"],
                "url": "https://markme.example.com",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        assert client.post("/api/v1/collections/defillama/trigger").status_code == 200

        run = client.post("/api/v1/run", json={})
        assert run.status_code == 200
        assert run.json()["data"]["project_count"] >= 1

        discoveries = client.get("/api/v1/discoveries?processed=true")
        assert discoveries.status_code == 200
        items = discoveries.json()["data"]["items"]
        assert any(i.get("processed") for i in items) or discoveries.json()["data"]["total"] >= 1

    @respx.mock
    def test_trigger_with_auto_run(self, client: TestClient, monkeypatch) -> None:
        """COLLECTION_AUTO_RUN_ENABLED 时 trigger 后自动分析。"""
        monkeypatch.setattr(settings, "collection_auto_run_enabled", True)
        protocols = [
            {
                "name": "AutoRun",
                "slug": "auto-run",
                "tvl": 8_000_000,
                "change_7d": 0.3,
                "category": "DeFi",
                "chains": ["Ethereum", "Base"],
                "url": "https://autorun.example.com",
                "twitter": "@autorun",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        response = client.post("/api/v1/collections/defillama/trigger")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data.get("auto_run") is not None
        assert data["auto_run"]["project_count"] >= 1
