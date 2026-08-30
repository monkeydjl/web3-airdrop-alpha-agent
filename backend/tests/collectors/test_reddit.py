"""Tests for the Reddit collector."""

import respx
from httpx import Response

from app.collectors.reddit import RedditCollector
from app.config import settings

SEARCH_RESULT = {
    "data": {
        "children": [
            {
                "data": {
                    "id": "abc123",
                    "title": "NovaLayer testnet airdrop is live",
                    "subreddit": "CryptoAirdrops",
                    "permalink": "/r/CryptoAirdrops/comments/abc123/title/",
                    "selftext": "Points program now open.",
                    "score": 450,
                    "num_comments": 85,
                }
            }
        ]
    }
}


def _enable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "reddit_enabled", True)
    monkeypatch.setattr(settings, "reddit_client_id", "cid")
    monkeypatch.setattr(settings, "reddit_client_secret", "secret")
    monkeypatch.setattr(settings, "reddit_username", "user")


def _mock_reddit(respx_mock, search_result=None) -> None:
    respx_mock.post("https://www.reddit.com/api/v1/access_token").return_value = Response(
        200, json={"access_token": "tok"}
    )
    respx_mock.get(url__startswith="https://oauth.reddit.com/search.json").return_value = Response(
        200, json=search_result or SEARCH_RESULT
    )


class TestRedditCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        _enable(monkeypatch)
        monkeypatch.setattr(settings, "reddit_enabled", False)
        assert not RedditCollector().is_enabled()

    def test_disabled_without_credentials(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "reddit_enabled", True)
        monkeypatch.setattr(settings, "reddit_client_id", "")
        monkeypatch.setattr(settings, "reddit_client_secret", "")
        monkeypatch.setattr(settings, "reddit_username", "")
        assert not RedditCollector().is_enabled()

    @respx.mock
    async def test_collect_signal_post(self, respx_mock, monkeypatch) -> None:
        _enable(monkeypatch)
        _mock_reddit(respx_mock)

        collector = RedditCollector()
        result = await collector.collect()
        assert result.status == "success"
        # SEARCH_TERMS 有 3 个词，mock 对每个词都返回同一条帖子 → 至少 1 条
        # （去重在持久化阶段做，采集器只负责原样吐出）。
        assert len(result.items) >= 1
        discovery = result.items[0]
        assert discovery.url == "https://reddit.com/r/CryptoAirdrops/comments/abc123/title/"
        assert discovery.sector is None
        assert discovery.discovery_score < 0.3

    @respx.mock
    async def test_collect_oauth_error(self, respx_mock, monkeypatch) -> None:
        _enable(monkeypatch)
        respx_mock.post("https://www.reddit.com/api/v1/access_token").return_value = Response(401)

        collector = RedditCollector()
        result = await collector.collect()
        assert result.status == "error"
