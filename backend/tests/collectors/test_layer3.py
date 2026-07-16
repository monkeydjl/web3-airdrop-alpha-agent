"""Tests for the Layer3 quest collector."""

import pytest
import respx
from httpx import Response

from app.collectors.layer3 import Layer3Collector
from app.config import settings


@pytest.fixture
def layer3_enabled(monkeypatch):
    """启用 Layer3 并配置测试 API key。"""
    monkeypatch.setattr(settings, "layer3_enabled", True)
    monkeypatch.setattr(settings, "layer3_api_key", "test_layer3_key")


class TestLayer3Collector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "layer3_enabled", False)
        monkeypatch.setattr(settings, "layer3_api_key", "key")
        collector = Layer3Collector()
        assert not collector.is_enabled()

    def test_disabled_without_key(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "layer3_enabled", True)
        monkeypatch.setattr(settings, "layer3_api_key", "")
        collector = Layer3Collector()
        assert not collector.is_enabled()

    @respx.mock
    async def test_collect_active_airdrop_task(self, layer3_enabled) -> None:
        payload = {
            "data": [
                {
                    "id": "t123",
                    "title": "NovaLayer Airdrop Quest",
                    "projectName": "NovaLayer",
                    "description": "Complete social tasks",
                    "status": "active",
                    "rewardType": "AIRDROP",
                    "chain": "ethereum",
                    "difficulty": "easy",
                    "xp": 100,
                }
            ]
        }
        respx.get("https://api.layer3.xyz/api/tasks").return_value = Response(200, json=payload)

        collector = Layer3Collector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.name == "NovaLayer"
        assert discovery.sector == "Quest"
        assert discovery.discovery_score > 0.5

    @respx.mock
    async def test_collect_empty_list(self, layer3_enabled) -> None:
        respx.get("https://api.layer3.xyz/api/tasks").return_value = Response(200, json={"data": []})

        collector = Layer3Collector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_api_error(self, layer3_enabled) -> None:
        respx.get("https://api.layer3.xyz/api/tasks").return_value = Response(500, json={"error": "Internal"})

        collector = Layer3Collector()
        result = await collector.collect()
        assert result.status == "error"
        assert result.error_message is not None
