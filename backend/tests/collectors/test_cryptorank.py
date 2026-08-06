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


class TestCryptoRankEconomicOptionA:
    """Option A: economic raw_data keeps provider None; legacy score/filter use local 0."""

    def _mid_item(self, **usd_overrides) -> dict:
        usd = {
            "price": 0.5,
            "volume24h": 2_000_000,
            "marketCap": 50_000_000,
            "percentChange24h": 5,
            "percentChange7d": 25,
        }
        usd.update(usd_overrides)
        return {
            "id": 100,
            "rank": 120,
            "slug": "midcap-token",
            "name": "MidCap Token",
            "symbol": "MID",
            "category": "DeFi",
            "type": "token",
            "values": {"USD": usd},
            "circulatingSupply": 1_000_000,
            "totalSupply": 2_000_000,
            "lastUpdated": "2026-07-09T00:00:00Z",
        }

    def test_missing_economic_fields_are_none_not_zero(self, collector) -> None:
        item = {
            "id": 200,
            "rank": 150,
            "slug": "sparse-token",
            "name": "Sparse Token",
            "symbol": "SPR",
            "category": "DeFi",
            "type": "token",
            "values": {"USD": {}},  # economic USD fields absent
            "lastUpdated": "2026-07-09T00:00:00Z",
        }
        # Need momentum or mid rank to pass filter; rank 150 is mid-tier
        discovery = collector._build_discovery(item)
        assert discovery is not None
        raw = discovery.raw_data
        for key in (
            "market_cap",
            "price",
            "volume_24h",
            "percent_change_24h",
            "percent_change_7d",
        ):
            assert raw.get(key) is None or key not in raw
            assert raw.get(key) != 0
        # supplies already optional
        assert raw.get("circulating_supply") is None
        assert raw.get("total_supply") is None

        item_null = {
            **self._mid_item(),
            "values": {
                "USD": {
                    "price": None,
                    "volume24h": None,
                    "marketCap": None,
                    "percentChange24h": None,
                    "percentChange7d": None,
                }
            },
            "circulatingSupply": None,
            "totalSupply": None,
        }
        # rank 120 mid-tier passes even with ch7 None → legacy 0, but mid-tier rank allows
        d_null = collector._build_discovery(item_null)
        assert d_null is not None
        raw_null = d_null.raw_data
        assert raw_null["market_cap"] is None
        assert raw_null["price"] is None
        assert raw_null["volume_24h"] is None
        assert raw_null["percent_change_24h"] is None
        assert raw_null["percent_change_7d"] is None
        assert raw_null["circulating_supply"] is None
        assert raw_null["total_supply"] is None

    def test_real_zero_preserved_in_raw_data(self, collector) -> None:
        item = self._mid_item(
            price=0,
            volume24h=0,
            marketCap=0,
            percentChange24h=0,
            percentChange7d=0,
        )
        item["circulatingSupply"] = 0
        item["totalSupply"] = 0
        discovery = collector._build_discovery(item)
        assert discovery is not None
        raw = discovery.raw_data
        assert raw["market_cap"] == 0
        assert raw["price"] == 0
        assert raw["volume_24h"] == 0
        assert raw["percent_change_24h"] == 0
        assert raw["percent_change_7d"] == 0
        assert raw["circulating_supply"] == 0
        assert raw["total_supply"] == 0
        assert raw["rank"] == 120

    def test_legacy_score_and_filter_unchanged_for_present_values(self, collector) -> None:
        item = self._mid_item()
        discovery = collector._build_discovery(item)
        assert discovery is not None
        expected = collector._calculate_discovery_score(
            rank=120,
            change_7d=25.0,
            volume_24h=2_000_000.0,
            market_cap=50_000_000.0,
        )
        assert discovery.discovery_score == expected
        assert discovery.raw_data["market_cap"] == 50_000_000
        mom = next(s for s in discovery.raw_signals if s.signal_type == "market_momentum")
        assert mom.signal_strength == min(1.0, max(0.0, abs(25.0) / 50.0))

    def test_legacy_score_zero_fallback_when_percent_change_missing(self, collector) -> None:
        item = self._mid_item()
        item["values"]["USD"].pop("percentChange7d", None)
        discovery = collector._build_discovery(item)
        assert discovery is not None
        expected = collector._calculate_discovery_score(
            rank=120,
            change_7d=0.0,
            volume_24h=2_000_000.0,
            market_cap=50_000_000.0,
        )
        assert discovery.discovery_score == expected
        assert (
            discovery.raw_data.get("percent_change_7d") is None
            or "percent_change_7d" not in discovery.raw_data
        )
