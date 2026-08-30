"""Tests for the Mirror collector (Arweave GraphQL)."""

import pytest
import respx
from httpx import Response

from app.collectors.mirror import MirrorCollector
from app.config import settings

PAYLOAD = {
    "data": {
        "transactions": {
            "edges": [
                {
                    "node": {
                        "id": "tx123",
                        "tags": [
                            {"name": "App-Name", "value": "Mirror"},
                            {"name": "Title", "value": "NovaLayer testnet airdrop"},
                            {"name": "Contributor", "value": "0xabc"},
                        ],
                    }
                }
            ]
        }
    }
}


@pytest.fixture
def mirror_enabled(monkeypatch):
    monkeypatch.setattr(settings, "mirror_enabled", True)


class TestMirrorCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "mirror_enabled", False)
        assert not MirrorCollector().is_enabled()

    @respx.mock
    async def test_collect_signal_article(self, mirror_enabled) -> None:
        respx.post("https://arweave.net/graphql").return_value = Response(200, json=PAYLOAD)

        collector = MirrorCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.url == "https://mirror.xyz/0xabc/tx123"
        assert discovery.sector is None
        assert discovery.discovery_score < 0.3

    @respx.mock
    async def test_collect_empty(self, mirror_enabled) -> None:
        respx.post("https://arweave.net/graphql").return_value = Response(
            200, json={"data": {"transactions": {"edges": []}}}
        )

        collector = MirrorCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_graphql_error(self, mirror_enabled) -> None:
        respx.post("https://arweave.net/graphql").return_value = Response(200, json={"errors": [{"message": "boom"}]})

        collector = MirrorCollector()
        result = await collector.collect()
        assert result.status == "error"
        assert "boom" in result.error_message
