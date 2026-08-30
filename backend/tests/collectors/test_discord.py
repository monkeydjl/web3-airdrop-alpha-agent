"""Tests for the Discord collector."""

import pytest
import respx
from httpx import Response

from app.collectors.discord import DiscordCollector
from app.config import settings

MESSAGES = [
    {
        "id": "msg123",
        "content": "NovaLayer testnet airdrop is live, points program open",
        "author": {"username": "mod"},
        "channel_id": "ch1",
        "timestamp": "2026-08-27T00:00:00Z",
    }
]


@pytest.fixture
def discord_enabled(monkeypatch):
    monkeypatch.setattr(settings, "discord_enabled", True)
    monkeypatch.setattr(settings, "discord_bot_token", "bot-tok")
    monkeypatch.setattr(settings, "discord_channel_id", "ch1")


class TestDiscordCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "discord_enabled", False)
        monkeypatch.setattr(settings, "discord_bot_token", "bot-tok")
        monkeypatch.setattr(settings, "discord_channel_id", "ch1")
        assert not DiscordCollector().is_enabled()

    def test_disabled_without_token_or_channel(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "discord_enabled", True)
        monkeypatch.setattr(settings, "discord_bot_token", "")
        monkeypatch.setattr(settings, "discord_channel_id", "")
        assert not DiscordCollector().is_enabled()

    @respx.mock
    async def test_collect_signal_message(self, discord_enabled) -> None:
        respx.get("https://discord.com/api/v10/channels/ch1/messages").return_value = Response(200, json=MESSAGES)

        collector = DiscordCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.url == "https://discord.com/channels/ch1/msg123"
        assert discovery.sector is None
        assert discovery.discovery_score < 0.3

    @respx.mock
    async def test_collect_empty_messages(self, discord_enabled) -> None:
        respx.get("https://discord.com/api/v10/channels/ch1/messages").return_value = Response(200, json=[])

        collector = DiscordCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_http_error(self, discord_enabled) -> None:
        respx.get("https://discord.com/api/v10/channels/ch1/messages").return_value = Response(403)

        collector = DiscordCollector()
        result = await collector.collect()
        assert result.status == "error"
