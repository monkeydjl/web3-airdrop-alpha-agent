"""Discord Collector.

通过 Discord Bot 读取配置频道的最新消息，采集社区活跃度类早期信号。

⚠️ 合规边界：Discord 服务条款禁止未经授权的规模化抓取。本采集器只读
**你自己有权限的服务器里、由你配置的单个频道**（bot 需在该频道拥有
READ_MESSAGE_HISTORY 权限），不做全站爬取、不跨服务器枚举。若用于你未
加入或未获授权的服务器，责任自负。

参考：
- DATA_SOURCE_STRATEGY.md §2（P2 源）
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.content_signals import detect_signal, extract_name
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings

logger = structlog.get_logger(__name__)

MAX_DISCOVERY_SCORE = 0.28

DISCORD_API_BASE = "https://discord.com/api/v10"
MESSAGE_LIMIT = 50


class DiscordCollector(DataCollector):
    """Discord 社区活跃度采集器（需 bot token + 频道 ID）。"""

    def __init__(self) -> None:
        super().__init__(source_id="discord", source_name="Discord")
        self.bot_token = settings.discord_bot_token
        self.channel_id = settings.discord_channel_id
        self.timeout = settings.discord_timeout
        self.retry = settings.discord_retry
        self.rate_limiter = TokenBucketRateLimiter("discord")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.discord_enabled and self.bot_token and self.channel_id)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bot {self.bot_token}"}

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            messages = await self._fetch_messages()
            self.logger.info("discord.fetched", message_count=len(messages))

            for message in messages:
                discovery = self._build_discovery(message)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("discord.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_messages(self) -> list[dict[str, Any]]:
        url = f"{DISCORD_API_BASE}/channels/{self.channel_id}/messages"
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                url,
                params={"limit": MESSAGE_LIMIT},
                headers=self._headers(),
            )
            response.raise_for_status()
            data = response.json()
        return [m for m in data if isinstance(m, dict)]

    def _build_discovery(self, message: dict[str, Any]) -> RawDiscovery | None:
        content = message.get("content") or ""
        if not content.strip():
            return None

        signal_type, signal_label = detect_signal(content)
        if signal_type is None:
            return None

        name = extract_name(content) or "Unknown"
        message_id = str(message.get("id") or "")
        author = (message.get("author") or {}).get("username") or ""

        raw_data = {
            "message_id": message_id,
            "author": author,
            "channel_id": message.get("channel_id") or self.channel_id,
            "timestamp": message.get("timestamp"),
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"author": author, "signal_type": signal_type},
                signal_strength=0.5,
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=message_id or f"discord-{datetime.now(UTC).timestamp()}",
            name=name,
            url=f"https://discord.com/channels/{self.channel_id}/{message_id}" if message_id else None,
            sector=None,
            stage="ideation",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=self._score(signal_type),
            discovered_at=datetime.now(UTC),
        )

    @staticmethod
    def _score(signal_type: str) -> float:
        type_map = {"funding": 0.13, "tge": 0.11, "testnet": 0.10, "points": 0.08, "airdrop": 0.06}
        return round(min(MAX_DISCOVERY_SCORE, 0.15 + type_map.get(signal_type, 0.05)), 4)

    async def health_check(self) -> dict[str, Any]:
        if not self.is_enabled():
            return {"source_id": self.source_id, "status": "disabled"}
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{DISCORD_API_BASE}/channels/{self.channel_id}/messages",
                    params={"limit": 1},
                    headers=self._headers(),
                )
                response.raise_for_status()
            return {"source_id": self.source_id, "status": "healthy"}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}
