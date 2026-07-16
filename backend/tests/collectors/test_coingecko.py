"""Tests for CoinGecko collector.

使用 respx mock CoinGecko API。
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.collectors.coingecko import CoinGeckoCollector
from app.config import settings


@pytest.fixture
def coingecko_collector(monkeypatch) -> CoinGeckoCollector:
    """创建 CoinGecko 采集器。"""
    monkeypatch.setattr(settings, "coingecko_enabled", True)
    monkeypatch.setattr(settings, "coingecko_api_key", "cg_test_key")
    return CoinGeckoCollector()


@respx.mock
def test_coingecko_collector_enabled(coingecko_collector: CoinGeckoCollector) -> None:
    """CoinGecko 默认启用。"""
    assert coingecko_collector.is_enabled()


@respx.mock
def test_coingecko_collector_disabled(monkeypatch) -> None:
    """关闭配置时禁用。"""
    monkeypatch.setattr(settings, "coingecko_enabled", False)
    collector = CoinGeckoCollector()
    assert not collector.is_enabled()


@respx.mock
async def test_coingecko_collect_success(coingecko_collector: CoinGeckoCollector) -> None:
    """模拟 CoinGecko /coins/markets 返回两条数据。"""
    route = respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=Response(
            200,
            json=[
                {
                    "id": "bitcoin",
                    "symbol": "btc",
                    "name": "Bitcoin",
                    "image": "https://example.com/btc.png",
                    "current_price": 50000,
                    "market_cap": 1000000000000,
                    "market_cap_rank": 1,
                    "total_volume": 30000000000,
                    "price_change_24h": 100,
                    "price_change_percentage_24h": 0.2,
                    "circulating_supply": 19000000,
                    "last_updated": "2026-07-09T00:00:00Z",
                },
                {
                    "id": "ethereum",
                    "symbol": "eth",
                    "name": "Ethereum",
                    "image": "https://example.com/eth.png",
                    "current_price": 3000,
                    "market_cap": 300000000000,
                    "market_cap_rank": 2,
                    "total_volume": 15000000000,
                    "price_change_24h": 10,
                    "price_change_percentage_24h": 0.3,
                    "circulating_supply": 120000000,
                    "last_updated": "2026-07-09T00:00:00Z",
                },
            ],
        )
    )

    result = await coingecko_collector.collect()

    assert result.status == "success"
    assert len(result.items) == 2
    assert route.called

    discovery = result.items[0]
    assert discovery.name == "Bitcoin"
    assert discovery.source_id == "coingecko"
    assert discovery.discovery_score == 0.1
    assert len(discovery.raw_signals) == 1

    signal = discovery.raw_signals[0]
    assert signal.signal_type == "token_listed"
    assert signal.signal_source == "coingecko"


@respx.mock
async def test_coingecko_collect_empty(coingecko_collector: CoinGeckoCollector) -> None:
    """返回空列表。"""
    route = respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(return_value=Response(200, json=[]))

    result = await coingecko_collector.collect()

    assert result.status == "partial"
    assert len(result.items) == 0
    assert route.called


@respx.mock
async def test_coingecko_collect_error(coingecko_collector: CoinGeckoCollector) -> None:
    """CoinGecko API 返回错误。"""
    respx.get("https://api.coingecko.com/api/v3/coins/markets").mock(
        return_value=Response(429, json={"message": "rate limit exceeded"})
    )

    result = await coingecko_collector.collect()

    assert result.status == "error"
    assert result.error_message is not None


def test_coingecko_signal_strength(coingecko_collector: CoinGeckoCollector) -> None:
    """信号强度按市值排名。"""
    assert coingecko_collector._calculate_signal_strength(1) == 1.0
    assert coingecko_collector._calculate_signal_strength(50) == 0.8
    assert coingecko_collector._calculate_signal_strength(200) == 0.6
    assert coingecko_collector._calculate_signal_strength(0) == 0.5


@respx.mock
async def test_coingecko_health_check(coingecko_collector: CoinGeckoCollector) -> None:
    """健康检查。"""
    respx.get("https://api.coingecko.com/api/v3/ping").mock(
        return_value=Response(200, json={"gecko_says": "(V3) To the Moon!"})
    )

    health = await coingecko_collector.health_check()

    assert health["source_id"] == "coingecko"
    assert health["status"] == "healthy"
    assert health["ping"] == {"gecko_says": "(V3) To the Moon!"}
