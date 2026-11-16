"""采集器分页完整性回归（2026-11-13 审查 P2-6）。

- etherscan getLogs：单请求最多返回 ~1000 条日志，超出部分**静默截断**
  （活跃区块范围里每小时都可能超限 → 聚合出的合约活动被系统性低估）。
  契约：跟随 page/offset 翻页直到不满页，页数封顶。
- farcaster castsByParent：Hubble 返回 `nextPageCursor`，此前固定取第一页
  25 条。契约：跟随 cursor 翻页，页数封顶。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from app.config import settings


def _log(address: str) -> dict:
    return {"address": address, "topics": [], "data": "0x0", "blockNumber": "0x1"}


@pytest.fixture
def _etherscan_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "etherscan_enabled", True)
    monkeypatch.setattr(settings, "etherscan_api_key", "test_key_123")


@pytest.fixture
def _farcaster_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "farcaster_enabled", True)


# ── etherscan getLogs 分页 ──────────────────────


@respx.mock
async def test_etherscan_getlogs_follows_pagination(_etherscan_enabled: None) -> None:
    from app.collectors.etherscan import EtherscanCollector

    collector = EtherscanCollector()
    collector.OFFSET_PER_PAGE = 2  # 缩小页大小让测试可用少量样本
    collector.MAX_LOG_PAGES = 3

    def _page_response(request: httpx.Request) -> Response:
        url = str(request.url)
        items = {"1": [_log("0xaaa"), _log("0xbbb")], "2": [_log("0xccc")], "3": []}[
            url.split("page=")[1].split("&")[0]
        ]
        return Response(200, json={"status": "1", "message": "OK", "result": items})

    route = respx.get(host="api.etherscan.io", path="/v2/api").mock(side_effect=_page_response)

    logs = await collector._fetch_transfer_logs(100, 200)

    assert [entry["address"] for entry in logs] == ["0xaaa", "0xbbb", "0xccc"], "第二页的日志被静默丢弃"
    assert route.call_count == 2, "不满页后不应再发请求"


@respx.mock
async def test_etherscan_getlogs_page_cap(_etherscan_enabled: None) -> None:
    """API 异常态（永远满页）下翻页必须封顶，不烧穿配额。"""
    from app.collectors.etherscan import EtherscanCollector

    collector = EtherscanCollector()
    collector.OFFSET_PER_PAGE = 2
    collector.MAX_LOG_PAGES = 3

    def _full_page(request: httpx.Request) -> Response:
        return Response(
            200,
            json={"status": "1", "message": "OK", "result": [_log("0xaaa"), _log("0xbbb")]},
        )

    respx.get(host="api.etherscan.io", path="/v2/api").mock(side_effect=_full_page)

    logs = await collector._fetch_transfer_logs(100, 200)

    assert len(logs) == 2 * collector.MAX_LOG_PAGES, "满页合并数量与请求页数不一致"
    assert len(logs) == 6


# ── farcaster cursor 分页 ───────────────────────


def _cast(text: str) -> dict:
    """Hubble 消息的真实形状：text 嵌在 data.castAddBody 里。"""
    return {"hash": "h", "data": {"fid": 1, "timestamp": 1, "castAddBody": {"text": text}}}


def _page_response_placeholder() -> None:
    return None


@respx.mock
async def test_farcaster_follows_next_page_cursor(_farcaster_enabled: None) -> None:
    from app.collectors.farcaster import FarcasterCollector

    collector = FarcasterCollector()
    collector.channels = ["python"]

    def _page_response(request: httpx.Request) -> Response:
        url = str(request.url)
        if "cursor=" in url:
            return Response(
                200,
                json={"messages": [_cast("page2-cast")], "nextPageCursor": ""},
            )
        return Response(
            200,
            json={"messages": [_cast("page1-cast")], "nextPageCursor": "cursor-2"},
        )

    respx.get(host="hub.pinata.cloud", path="/v1/castsByParent").mock(side_effect=_page_response)

    items = await collector._fetch_items()

    texts = [item["text"] for item in items]
    assert "page1-cast" in texts and "page2-cast" in texts, f"cursor 第二页被丢弃：{texts}"


@respx.mock
async def test_farcaster_cursor_page_cap(_farcaster_enabled: None) -> None:
    """永远有 next cursor 时翻页必须封顶。"""
    from app.collectors.farcaster import FarcasterCollector

    collector = FarcasterCollector()
    collector.channels = ["python"]

    state = {"calls": 0}

    def _always_more(request: httpx.Request) -> Response:
        state["calls"] += 1
        return Response(
            200,
            json={"messages": [_cast(f"cast-{state['calls']}")], "nextPageCursor": f"c-{state['calls']}"},
        )

    respx.get(host="hub.pinata.cloud", path="/v1/castsByParent").mock(side_effect=_always_more)

    items = await collector._fetch_items()

    assert state["calls"] == collector.MAX_CURSOR_PAGES, "cursor 翻页未封顶"
    assert len(items) == collector.MAX_CURSOR_PAGES
