"""Tests for the Galxe quest collector."""

import pytest
import respx
from httpx import Response

from app.collectors.galxe import GalxeCollector
from app.config import settings


@pytest.fixture
def galxe_enabled(monkeypatch):
    """启用 Galxe 并配置测试 API key。"""
    monkeypatch.setattr(settings, "galxe_enabled", True)
    monkeypatch.setattr(settings, "galxe_api_key", "test_galxe_key")


class TestGalxeCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "galxe_enabled", False)
        monkeypatch.setattr(settings, "galxe_api_key", "key")
        collector = GalxeCollector()
        assert not collector.is_enabled()

    def test_disabled_without_key(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "galxe_enabled", True)
        monkeypatch.setattr(settings, "galxe_api_key", "")
        collector = GalxeCollector()
        assert not collector.is_enabled()

    @respx.mock
    async def test_collect_active_token_campaign(self, galxe_enabled) -> None:
        payload = {
            "data": {
                "campaignList": {
                    "list": [
                        {
                            "id": "gc123",
                            "name": "NovaLayer Early Adopters",
                            "description": "Join the testnet and earn tokens",
                            "status": "ACTIVE",
                            "rewardType": "TOKEN",
                            "thumbnail": "https://example.com/thumb.png",
                            "space": {"id": "sp1", "name": "NovaLayer", "alias": "novalayer"},
                        }
                    ]
                }
            }
        }
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(200, json=payload)

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.name == "NovaLayer"
        assert discovery.sector == "Quest"
        assert discovery.discovery_score > 0.5

    @respx.mock
    async def test_collect_graphql_error(self, galxe_enabled) -> None:
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(
            200, json={"errors": [{"message": "unauthorized"}]}
        )

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "error"
        assert "unauthorized" in result.error_message

    @respx.mock
    async def test_collect_empty_list(self, galxe_enabled) -> None:
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(
            200, json={"data": {"campaignList": {"list": []}}}
        )

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []
