"""Tests for Farcaster public hub collector."""

from datetime import UTC, datetime

import pytest
import respx
from httpx import Response

from app.collectors.farcaster import (
    FARCASTER_EPOCH_OFFSET,
    FarcasterCollector,
    farcaster_time_to_datetime,
)
from app.config import settings

SAMPLE_HUB_RESPONSE = {
    "messages": [
        {
            "data": {
                "type": "MESSAGE_TYPE_CAST_ADD",
                "fid": 8888,
                "timestamp": 110000000,  # Farcaster epoch
                "network": "FARCASTER_NETWORK_MAINNET",
                "castAddBody": {
                    "embeds": [{"url": "https://novalayer.xyz"}],
                    "mentions": [],
                    "parentUrl": "https://farcaster.xyz/~/channel/airdrop",
                    "text": "NovaLayer testnet airdrop guide! Join testnet and earn points: https://novalayer.xyz",
                    "mentionsPositions": [],
                },
            },
            "hash": "0x4a5b6c7d8e",
            "hashScheme": "HASH_SCHEME_BLAKE3",
            "signature": "0x...",
            "signer": "0x...",
        },
        {
            "data": {
                "type": "MESSAGE_TYPE_CAST_ADD",
                "fid": 9999,
                "timestamp": 110000100,
                "network": "FARCASTER_NETWORK_MAINNET",
                "castAddBody": {
                    "embeds": [],
                    "mentions": [],
                    "parentUrl": "https://farcaster.xyz/~/channel/airdrop",
                    "text": "Good morning Farcaster! What are you building today?",
                    "mentionsPositions": [],
                },
            },
            "hash": "0x999999",
            "hashScheme": "HASH_SCHEME_BLAKE3",
            "signature": "0x...",
            "signer": "0x...",
        },
    ],
    "nextPageToken": "",
}

SAMPLE_NO_SIGNAL_RESPONSE = {
    "messages": [
        {
            "data": {
                "type": "MESSAGE_TYPE_CAST_ADD",
                "fid": 1234,
                "timestamp": 110000200,
                "network": "FARCASTER_NETWORK_MAINNET",
                "castAddBody": {
                    "embeds": [],
                    "mentions": [],
                    "parentUrl": "https://farcaster.xyz/~/channel/airdrop",
                    "text": "Just having coffee and enjoying the weekend.",
                    "mentionsPositions": [],
                },
            },
            "hash": "0x111111",
        }
    ]
}


@pytest.fixture
def farcaster_enabled(monkeypatch):
    monkeypatch.setattr(settings, "farcaster_enabled", True)
    monkeypatch.setattr(settings, "farcaster_hub_url", "https://hub.pinata.cloud")
    monkeypatch.setattr(settings, "farcaster_channels", "airdrop")


class TestFarcasterTimeConversion:
    def test_epoch_conversion(self):
        fc_sec = 1000
        dt = farcaster_time_to_datetime(fc_sec)
        assert dt == datetime.fromtimestamp(FARCASTER_EPOCH_OFFSET + 1000, tz=UTC)

    def test_none_epoch_returns_now(self):
        dt = farcaster_time_to_datetime(None)
        assert dt.tzinfo == UTC


class TestFarcasterCollector:
    def test_disabled_without_flag(self, monkeypatch):
        monkeypatch.setattr(settings, "farcaster_enabled", False)
        assert not FarcasterCollector().is_enabled()

    def test_channel_parsing(self, monkeypatch):
        monkeypatch.setattr(settings, "farcaster_channels", "/chan1, chan2 , /chan3")
        collector = FarcasterCollector()
        assert collector.channels == ["chan1", "chan2", "chan3"]

    def test_channel_fallback_default(self, monkeypatch):
        monkeypatch.setattr(settings, "farcaster_channels", "  , ")
        collector = FarcasterCollector()
        assert collector.channels == ["airdrop", "airdrops", "testnet"]

    @respx.mock
    async def test_collect_signal_cast(self, farcaster_enabled):
        respx.get(
            "https://hub.pinata.cloud/v1/castsByParent?url=https://farcaster.xyz/~/channel/airdrop&pageSize=25&reverse=1"
        ).return_value = Response(200, json=SAMPLE_HUB_RESPONSE)

        collector = FarcasterCollector()
        result = await collector.collect()

        assert result.status == "success"
        assert len(result.items) == 1  # only first cast has airdrop signal

        discovery = result.items[0]
        assert discovery.source_id == "farcaster"
        assert discovery.raw_id == "fc-0x4a5b6c7d8e"
        assert discovery.name == "Novalayer"
        assert discovery.discovery_score <= 0.28
        assert discovery.stage == "ideation"
        assert discovery.url == "https://warpcast.com/~/conversations/0x4a5b6c7d8e"
        assert len(discovery.raw_signals) == 1
        assert discovery.raw_signals[0].signal_type == "community_activity"
        assert discovery.raw_signals[0].signal_data["cast_hash"] == "0x4a5b6c7d8e"

    @respx.mock
    async def test_collect_no_signal_skips(self, farcaster_enabled):
        respx.get(
            "https://hub.pinata.cloud/v1/castsByParent?url=https://farcaster.xyz/~/channel/airdrop&pageSize=25&reverse=1"
        ).return_value = Response(200, json=SAMPLE_NO_SIGNAL_RESPONSE)

        collector = FarcasterCollector()
        result = await collector.collect()

        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_partial_channel_failure(self, monkeypatch):
        monkeypatch.setattr(settings, "farcaster_enabled", True)
        monkeypatch.setattr(settings, "farcaster_hub_url", "https://hub.pinata.cloud")
        monkeypatch.setattr(settings, "farcaster_channels", "chan_fail,chan_ok")

        respx.get(
            "https://hub.pinata.cloud/v1/castsByParent?url=https://farcaster.xyz/~/channel/chan_fail&pageSize=25&reverse=1"
        ).return_value = Response(500)
        respx.get(
            "https://hub.pinata.cloud/v1/castsByParent?url=https://farcaster.xyz/~/channel/chan_ok&pageSize=25&reverse=1"
        ).return_value = Response(200, json=SAMPLE_HUB_RESPONSE)

        collector = FarcasterCollector()
        result = await collector.collect()

        assert result.status == "success"
        assert len(result.items) == 1
        assert result.items[0].raw_id == "fc-0x4a5b6c7d8e"

    @respx.mock
    async def test_collect_all_channels_error(self, farcaster_enabled):
        respx.get(
            "https://hub.pinata.cloud/v1/castsByParent?url=https://farcaster.xyz/~/channel/airdrop&pageSize=25&reverse=1"
        ).return_value = Response(500)

        collector = FarcasterCollector()
        result = await collector.collect()

        assert result.status == "error"
        assert result.items == []
        assert result.error_message is not None
