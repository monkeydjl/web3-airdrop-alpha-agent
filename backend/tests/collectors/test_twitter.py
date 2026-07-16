"""Tests for Twitter/X collector.

使用 respx mock Twitter API v2 响应。
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.collectors.twitter import (
    DEFAULT_KEYWORDS,
    DEFAULT_KOL_ACCOUNTS,
    TwitterKeywordCollector,
    TwitterKolCollector,
)
from app.config import settings


@pytest.fixture
def _twitter_enabled(monkeypatch):
    """启用 Twitter 并配置测试 token。"""
    monkeypatch.setattr(settings, "twitter_enabled", True)
    monkeypatch.setattr(settings, "twitter_bearer_token", "test_bearer_token")


def sample_tweet(
    tweet_id: str = "1234567890",
    text: str = "New testnet for LayerX is live! #testnet #points",
    author_id: str = "9876543210",
    like_count: int = 100,
    retweet_count: int = 50,
    reply_count: int = 10,
    created_at: str = "2026-07-09T00:00:00Z",
) -> dict:
    return {
        "id": tweet_id,
        "text": text,
        "author_id": author_id,
        "created_at": created_at,
        "lang": "en",
        "public_metrics": {
            "like_count": like_count,
            "retweet_count": retweet_count,
            "reply_count": reply_count,
            "quote_count": 5,
            "impression_count": 1000,
        },
    }


def test_kol_collector_enabled(_twitter_enabled) -> None:
    """配置 token 后 KOL 采集器启用。"""
    collector = TwitterKolCollector()
    assert collector.is_enabled()


def test_keyword_collector_enabled(_twitter_enabled) -> None:
    """配置 token 后关键词采集器启用。"""
    collector = TwitterKeywordCollector()
    assert collector.is_enabled()


def test_kol_collector_disabled_without_token(monkeypatch) -> None:
    """无 bearer token 时禁用。"""
    monkeypatch.setattr(settings, "twitter_enabled", True)
    monkeypatch.setattr(settings, "twitter_bearer_token", "")
    collector = TwitterKolCollector()
    assert not collector.is_enabled()


def test_keyword_collector_disabled_when_flag_off(monkeypatch) -> None:
    """twitter_enabled=false 时禁用。"""
    monkeypatch.setattr(settings, "twitter_enabled", False)
    monkeypatch.setattr(settings, "twitter_bearer_token", "test_bearer_token")
    collector = TwitterKeywordCollector()
    assert not collector.is_enabled()


def test_default_kol_accounts() -> None:
    """默认监听账号符合策略文档。"""
    assert "a16z" in DEFAULT_KOL_ACCOUNTS
    assert "paradigm" in DEFAULT_KOL_ACCOUNTS


def test_default_keywords() -> None:
    """默认关键词符合策略文档。"""
    assert "#airdrop" in DEFAULT_KEYWORDS
    assert "#testnet" in DEFAULT_KEYWORDS


class TestTwitterSignalExtraction:
    def test_detect_signal_type(self, _twitter_enabled) -> None:
        """检测信号关键词。"""
        collector = TwitterKeywordCollector()
        assert collector._detect_signal_type("testnet is live") == ("testnet", "testnet")
        assert collector._detect_signal_type("new points program") == ("points", "points")
        assert collector._detect_signal_type("raised funding") == ("funding", "funding")
        assert collector._detect_signal_type("hello world") == (None, None)

    def test_extract_project_name_from_url(self, _twitter_enabled) -> None:
        """从 URL 提取项目名。"""
        collector = TwitterKeywordCollector()
        text = "Check out https://layerx.xyz/testnet for the new testnet"
        assert collector._extract_project_name(text) == "Layerx"

    def test_extract_project_name_from_handle(self, _twitter_enabled) -> None:
        """从 @handle 提取项目名（排除知名账号，且 handle 非大写开头时走此路径）。"""
        collector = TwitterKeywordCollector()
        text = "@layerxprotocol just launched their testnet"
        assert collector._extract_project_name(text) == "Layerxprotocol"

    def test_extract_project_name_from_capitalized_word(self, _twitter_enabled) -> None:
        """从首字母大写词/CamelCase 提取项目名。"""
        collector = TwitterKeywordCollector()
        text = "AuroraDex is the new DEX on testnet"
        assert collector._extract_project_name(text) == "AuroraDex"

    def test_build_discovery(self, _twitter_enabled) -> None:
        """把推文转换为 RawDiscovery。"""
        collector = TwitterKeywordCollector()
        tweet = sample_tweet()
        discovery = collector._build_discovery(tweet)

        assert discovery is not None
        assert discovery.name == "LayerX"
        assert discovery.source_id == "twitter_keyword"
        assert discovery.discovery_score > 0
        assert len(discovery.raw_signals) == 1
        assert discovery.raw_signals[0].signal_type == "twitter_mention"
        assert discovery.raw_signals[0].signal_source == "twitter"

    def test_build_discovery_ignores_noise(self, _twitter_enabled) -> None:
        """没有信号关键词的推文不生成发现。"""
        collector = TwitterKeywordCollector()
        tweet = sample_tweet(text="Just a regular tweet about the weather")
        assert collector._build_discovery(tweet) is None


class TestTwitterEngagementAndScore:
    def test_engagement_strength(self, _twitter_enabled) -> None:
        """互动量计算在 0-1 之间。"""
        collector = TwitterKeywordCollector()
        strength = collector._calculate_engagement_strength(1000, 500, 100)
        assert 0 <= strength <= 1

    def test_discovery_score_kol_higher(self, _twitter_enabled) -> None:
        """KOL 来源的发现分高于关键词来源。"""
        kol = TwitterKolCollector()
        keyword = TwitterKeywordCollector()

        kol_score = kol._calculate_discovery_score(
            signal_type="funding", likes=1000, retweets=500, replies=100, source_id="twitter_kol"
        )
        keyword_score = keyword._calculate_discovery_score(
            signal_type="funding", likes=1000, retweets=500, replies=100, source_id="twitter_keyword"
        )
        assert kol_score > keyword_score


@pytest.mark.asyncio
class TestTwitterKolCollect:
    @respx.mock
    async def test_collect_success(self, _twitter_enabled) -> None:
        """模拟 KOL 采集返回一条推文。"""
        collector = TwitterKolCollector()
        # KOL 监听使用 search/recent，query 包含 from:handle
        route = respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        sample_tweet(
                            tweet_id="1",
                            text="Excited to announce testnet for NovaLayer! #testnet",
                        ),
                    ],
                },
            )
        )

        result = await collector.collect()

        assert result.status in {"success", "partial"}
        assert len(result.items) >= 1
        assert route.called

        # 找到 NovaLayer 发现（CamelCase 应被正确提取）
        names = {item.name for item in result.items}
        assert "NovaLayer" in names, f"got names: {names}"

    @respx.mock
    async def test_collect_empty(self, _twitter_enabled) -> None:
        """返回空推文列表。"""
        collector = TwitterKolCollector()
        respx.get("https://api.twitter.com/2/tweets/search/recent").mock(return_value=Response(200, json={"data": []}))

        result = await collector.collect()

        assert result.status == "partial"
        assert len(result.items) == 0

    @respx.mock
    async def test_collect_error(self, _twitter_enabled) -> None:
        """Twitter API 返回错误。"""
        collector = TwitterKolCollector()
        respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
            return_value=Response(401, json={"title": "Unauthorized"})
        )

        result = await collector.collect()

        assert result.status == "error"
        assert result.error_message is not None


@pytest.mark.asyncio
class TestTwitterKeywordCollect:
    @respx.mock
    async def test_collect_success(self, _twitter_enabled) -> None:
        """模拟关键词采集返回一条推文。"""
        collector = TwitterKeywordCollector()
        route = respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        sample_tweet(
                            tweet_id="2",
                            text="New points program by YieldMax, earn points now! #points",
                        ),
                    ],
                },
            )
        )

        result = await collector.collect()

        assert result.status in {"success", "partial"}
        assert route.called
        # 每个关键词都查询，但只返回了一条数据，所以至少有一个发现
        assert len(result.items) >= 1

    @respx.mock
    async def test_collect_handles_no_signal_tweets(self, _twitter_enabled) -> None:
        """关键词返回但无信号关键词时不生成发现。"""
        collector = TwitterKeywordCollector()
        respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
            return_value=Response(
                200,
                json={
                    "data": [
                        sample_tweet(text="Random tweet without project signal"),
                    ],
                },
            )
        )

        result = await collector.collect()

        assert result.status == "partial"
        assert len(result.items) == 0


@pytest.mark.asyncio
class TestTwitterHealthCheck:
    @respx.mock
    async def test_health_check_healthy(self, _twitter_enabled) -> None:
        """健康检查成功。"""
        collector = TwitterKeywordCollector()
        respx.get("https://api.twitter.com/2/tweets/search/recent").mock(
            return_value=Response(200, json={"data": [{"id": "1"}]})
        )

        health = await collector.health_check()

        assert health["source_id"] == "twitter_keyword"
        assert health["status"] == "healthy"
        assert health["tweet_count"] == 1

    @respx.mock
    async def test_health_check_unhealthy(self, _twitter_enabled) -> None:
        """健康检查失败。"""
        collector = TwitterKeywordCollector()
        respx.get("https://api.twitter.com/2/tweets/search/recent").mock(return_value=Response(401))

        health = await collector.health_check()

        assert health["status"] == "unhealthy"
        assert "error" in health
