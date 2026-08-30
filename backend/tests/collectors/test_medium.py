"""Tests for the Medium collector."""

import pytest
import respx
from httpx import Response

from app.collectors.medium import MediumCollector
from app.config import settings

RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel>
<item>
<title>NovaLayer testnet airdrop guide</title>
<link>https://medium.com/@novalayer/testnet-airdrop-guide</link>
<description>Join the testnet and earn points.</description>
<dc:creator>NovaLayer</dc:creator>
<pubDate>Wed, 27 Aug 2026 00:00:00 GMT</pubDate>
</item>
</channel>
</rss>
"""

RSS_NO_SIGNAL = """<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:dc="http://purl.org/dc/elements/1.1/" version="2.0">
<channel>
<item>
<title>Market recap for the week</title>
<link>https://medium.com/@analyst/market-recap</link>
<description>Nothing to see here.</description>
</item>
</channel>
</rss>
"""


@pytest.fixture
def medium_enabled(monkeypatch):
    monkeypatch.setattr(settings, "medium_enabled", True)
    monkeypatch.setattr(settings, "medium_tags", "airdrop")


class TestMediumCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "medium_enabled", False)
        assert not MediumCollector().is_enabled()

    @respx.mock
    async def test_collect_signal_article(self, medium_enabled) -> None:
        respx.get("https://medium.com/feed/tag/airdrop").return_value = Response(200, text=RSS)

        collector = MediumCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.name == "NovaLayer"
        assert discovery.sector is None
        assert discovery.discovery_score < 0.3  # 内容源不触发 LLM 分析

    @respx.mock
    async def test_collect_no_signal_skips(self, medium_enabled) -> None:
        respx.get("https://medium.com/feed/tag/airdrop").return_value = Response(200, text=RSS_NO_SIGNAL)

        collector = MediumCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_http_error(self, medium_enabled) -> None:
        respx.get("https://medium.com/feed/tag/airdrop").return_value = Response(500)

        collector = MediumCollector()
        result = await collector.collect()
        assert result.status == "error"
        assert result.items == []
