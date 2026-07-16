"""Unit tests for CryptoRankCollector (no live network)."""

from __future__ import annotations

import pytest

from app.collectors.cryptorank import CryptoRankCollector
from app.config import settings


@pytest.fixture
def collector(monkeypatch):
    monkeypatch.setattr(settings, "cryptorank_enabled", True)
    monkeypatch.setattr(settings, "cryptorank_api_key", "test-key")
    monkeypatch.setattr(settings, "cryptorank_base_url", "https://api.cryptorank.io/v1")
    return CryptoRankCollector()


class TestCryptoRankCollector:
    def test_disabled_without_key(self, monkeypatch):
        monkeypatch.setattr(settings, "cryptorank_enabled", True)
        monkeypatch.setattr(settings, "cryptorank_api_key", "")
        c = CryptoRankCollector()
        assert c.is_enabled() is False

    def test_enabled_with_key(self, collector):
        assert collector.is_enabled() is True
        assert collector.source_id == "cryptorank"

    @pytest.mark.asyncio
    async def test_collect_filters_top_ranks(self, collector, monkeypatch):
        async def fake_fetch():
            return [
                {
                    "id": 1,
                    "rank": 1,
                    "slug": "bitcoin",
                    "name": "Bitcoin",
                    "symbol": "BTC",
                    "category": "Currency",
                    "type": "coin",
                    "values": {
                        "USD": {
                            "price": 1,
                            "volume24h": 1e9,
                            "marketCap": 1e12,
                            "percentChange24h": 1,
                            "percentChange7d": 2,
                        }
                    },
                },
                {
                    "id": 100,
                    "rank": 120,
                    "slug": "midcap-token",
                    "name": "MidCap Token",
                    "symbol": "MID",
                    "category": "DeFi",
                    "type": "token",
                    "values": {
                        "USD": {
                            "price": 0.5,
                            "volume24h": 2_000_000,
                            "marketCap": 50_000_000,
                            "percentChange24h": 5,
                            "percentChange7d": 25,
                        }
                    },
                },
            ]

        monkeypatch.setattr(collector, "_fetch_currencies", fake_fetch)
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        item = result.items[0]
        assert item.name == "MidCap Token"
        assert item.sector == "DeFi"
        assert 0.05 <= item.discovery_score <= 0.28
        assert item.raw_signals

    def test_discovery_score_bounds(self, collector):
        s = collector._calculate_discovery_score(rank=100, change_7d=40.0, volume_24h=5_000_000, market_cap=1e8)
        assert 0.05 <= s <= 0.28
