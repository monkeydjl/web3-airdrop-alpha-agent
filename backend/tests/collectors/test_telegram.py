"""Tests for Telegram channel collector."""

import pytest
import respx
from httpx import Response

from app.collectors.telegram import TelegramChannelCollector, TelegramWebParser
from app.config import settings

SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<body>
  <div class="tgme_channel_info">
    <div class="tgme_channel_info_header">Airdrop Inspect</div>
  </div>
  <div class="tgme_widget_message" data-post="airdropinspect/1001">
    <a class="tgme_widget_message_date" href="https://t.me/airdropinspect/1001">
      <time datetime="2026-09-20T10:00:00+00:00">Sep 20, 2026</time>
    </a>
    <div class="tgme_widget_message_text">
      NovaLayer testnet airdrop is now live!<br>
      Join the incentivized testnet and earn points.<br>
      Guide: https://novalayer.xyz
    </div>
  </div>
  <div class="tgme_widget_message" data-post="airdropinspect/1002">
    <a class="tgme_widget_message_date" href="https://t.me/airdropinspect/1002">
      <time datetime="2026-09-20T11:00:00+00:00">Sep 20, 2026</time>
    </a>
    <div class="tgme_widget_message_text">
      General market chat with no signals here.
    </div>
  </div>
</body>
</html>
"""

SAMPLE_HTML_NO_SIGNAL = """
<!DOCTYPE html>
<html>
<body>
  <div class="tgme_widget_message" data-post="airdropinspect/2001">
    <div class="tgme_widget_message_text">
      Good morning everyone! Have a great Sunday.
    </div>
  </div>
</body>
</html>
"""


@pytest.fixture
def telegram_enabled(monkeypatch):
    monkeypatch.setattr(settings, "telegram_enabled", True)
    monkeypatch.setattr(settings, "telegram_channels", "airdropinspect")


class TestTelegramWebParser:
    def test_parse_messages_success(self):
        parser = TelegramWebParser("airdropinspect")
        parser.feed(SAMPLE_HTML)
        assert len(parser.messages) == 2

        msg1 = parser.messages[0]
        assert msg1["post_id"] == "1001"
        assert msg1["channel"] == "airdropinspect"
        assert "NovaLayer testnet airdrop" in msg1["text"]
        assert "\n" in msg1["text"]  # <br> converted to newline
        assert msg1["datetime"] == "2026-09-20T10:00:00+00:00"
        assert msg1["url"] == "https://t.me/airdropinspect/1001"

        msg2 = parser.messages[1]
        assert msg2["post_id"] == "1002"
        assert "General market chat" in msg2["text"]

    def test_parse_empty_or_no_text(self):
        empty_html = '<div class="tgme_widget_message" data-post="airdropinspect/999"></div>'
        parser = TelegramWebParser("airdropinspect")
        parser.feed(empty_html)
        assert len(parser.messages) == 0


class TestTelegramChannelCollector:
    def test_disabled_without_flag(self, monkeypatch):
        monkeypatch.setattr(settings, "telegram_enabled", False)
        assert not TelegramChannelCollector().is_enabled()

    def test_channel_parsing(self, monkeypatch):
        monkeypatch.setattr(settings, "telegram_channels", "@chan1, chan2 , @chan3")
        collector = TelegramChannelCollector()
        assert collector.channels == ["chan1", "chan2", "chan3"]

    def test_channel_fallback_default(self, monkeypatch):
        monkeypatch.setattr(settings, "telegram_channels", "  , ")
        collector = TelegramChannelCollector()
        assert collector.channels == ["airdropinspect"]

    @respx.mock
    async def test_collect_signal_message(self, telegram_enabled):
        respx.get("https://t.me/s/airdropinspect").return_value = Response(200, text=SAMPLE_HTML)

        collector = TelegramChannelCollector()
        result = await collector.collect()

        assert result.status == "success"
        assert len(result.items) == 1  # 1001 has signal, 1002 does not

        discovery = result.items[0]
        assert discovery.source_id == "telegram"
        assert discovery.raw_id == "tg-airdropinspect-1001"
        assert discovery.name == "Novalayer"
        assert discovery.discovery_score <= 0.28  # P2 content source score capped
        assert discovery.stage == "ideation"
        assert len(discovery.raw_signals) == 1
        assert discovery.raw_signals[0].signal_type == "community_activity"

    @respx.mock
    async def test_collect_no_signal_skips(self, telegram_enabled):
        respx.get("https://t.me/s/airdropinspect").return_value = Response(200, text=SAMPLE_HTML_NO_SIGNAL)

        collector = TelegramChannelCollector()
        result = await collector.collect()

        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_partial_channel_failure(self, monkeypatch):
        monkeypatch.setattr(settings, "telegram_enabled", True)
        monkeypatch.setattr(settings, "telegram_channels", "chan_fail,chan_ok")

        respx.get("https://t.me/s/chan_fail").return_value = Response(500)
        respx.get("https://t.me/s/chan_ok").return_value = Response(200, text=SAMPLE_HTML)

        collector = TelegramChannelCollector()
        result = await collector.collect()

        assert result.status == "success"
        assert len(result.items) == 1
        assert result.items[0].raw_id == "tg-chan_ok-1001"

    @respx.mock
    async def test_collect_all_channels_error(self, telegram_enabled):
        respx.get("https://t.me/s/airdropinspect").return_value = Response(500)

        collector = TelegramChannelCollector()
        result = await collector.collect()

        assert result.status == "error"
        assert result.items == []
        assert result.error_message is not None
