"""Twitter search/recent 分页回归（2026-11-13 审查 P2-6）。

背景：`_search_recent` 只取第一页 —— `meta.next_token` 被直接丢弃。
twitter_keyword 每 15 分钟一轮、search/recent 窗口重叠，第一页（≤50 条）
之外的讨论全部漏采；重复窗口下漏采的部分恰恰是热度统计的输入。

契约：
- 响应带 `meta.next_token` 时跟随翻页，合并各页 tweets；
- 无 next_token / 空页即停（不浪费请求）；
- 页数封顶 MAX_PAGES_PER_QUERY，防失控翻页。
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.config import settings


@pytest.fixture
def _twitter_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "twitter_enabled", True)
    monkeypatch.setattr(settings, "twitter_bearer_token", "test_bearer_token")


def _tweet(tweet_id: str) -> dict:
    return {"id": tweet_id, "text": "gm", "author_id": "a1"}


@respx.mock
async def test_follows_next_token_and_merges_pages(_twitter_enabled: None) -> None:
    from app.collectors.twitter import TwitterKeywordCollector

    collector = TwitterKeywordCollector()
    route = respx.get(path="/2/tweets/search/recent").mock(
        side_effect=[
            Response(200, json={"data": [_tweet("1")], "meta": {"next_token": "tok-2"}}),
            Response(200, json={"data": [_tweet("2"), _tweet("3")], "meta": {}}),
        ]
    )

    async with collector.http_client(timeout=collector.timeout) as client:
        tweets = await collector._search_recent("#airdrop", max_results=25, client=client)

    assert [t["id"] for t in tweets] == ["1", "2", "3"], "第二页的推文被丢弃"
    assert route.call_count == 2, "无 next_token 后不应再发请求"


@respx.mock
async def test_page_cap_limits_requests(_twitter_enabled: None) -> None:
    from app.collectors.twitter import TwitterKeywordCollector

    collector = TwitterKeywordCollector()
    route = respx.get(path="/2/tweets/search/recent").mock(
        side_effect=lambda request: Response(
            200, json={"data": [_tweet("x")], "meta": {"next_token": f"tok-{route.call_count + 1}"}}
        )
    )

    async with collector.http_client(timeout=collector.timeout) as client:
        tweets = await collector._search_recent("#airdrop", max_results=25, client=client)

    assert route.call_count == collector.MAX_PAGES_PER_QUERY, f"翻页未封顶：{route.call_count} 次请求"
    assert len(tweets) == collector.MAX_PAGES_PER_QUERY


@respx.mock
async def test_single_page_without_meta_makes_one_request(_twitter_enabled: None) -> None:
    """既有单页行为不得回归：无 meta.next_token 时只发 1 次请求。"""
    from app.collectors.twitter import TwitterKeywordCollector

    collector = TwitterKeywordCollector()
    route = respx.get(path="/2/tweets/search/recent").mock(return_value=Response(200, json={"data": [_tweet("1")]}))

    async with collector.http_client(timeout=collector.timeout) as client:
        tweets = await collector._search_recent("#airdrop", max_results=25, client=client)

    assert [t["id"] for t in tweets] == ["1"]
    assert route.call_count == 1


@respx.mock
async def test_empty_page_stops_pagination(_twitter_enabled: None) -> None:
    """带 next_token 但 data 为空 → 停止（防 API 异常态下无限空转）。"""
    from app.collectors.twitter import TwitterKeywordCollector

    collector = TwitterKeywordCollector()
    route = respx.get(path="/2/tweets/search/recent").mock(
        side_effect=[
            Response(200, json={"data": [], "meta": {"next_token": "tok-2"}}),
            Response(200, json={"data": [_tweet("late")], "meta": {}}),
        ]
    )

    async with collector.http_client(timeout=collector.timeout) as client:
        tweets = await collector._search_recent("#airdrop", max_results=25, client=client)

    assert tweets == []
    assert route.call_count == 1
