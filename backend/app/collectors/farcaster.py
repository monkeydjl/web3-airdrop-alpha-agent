"""Farcaster Public Hub Collector.

从 Farcaster 公开免费 Hubble 节点（默认 https://hub.pinata.cloud）采集频道的最新 Casts。
提取海外真实 Founder/Dev 早期空投与 Alpha 信号。
完全免费，无需 API Key、无需账号登录，零 API 成本。

参考：
- DATA_SOURCE_STRATEGY.md §2（P2 源）
- ADR-012-system-direction-auto-scan.md
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
from app.utils.domain_allowlist import assert_url_allowed

logger = structlog.get_logger(__name__)

# 内容源是二阶信号（内容里"提到"项目），不是项目目录：discovery_score 上限
# 刻意压在分析阈值 0.3 以下，只贡献 project_signals，不触发 LLM 分析（§5.4）。
MAX_DISCOVERY_SCORE = 0.28

# Farcaster Epoch: 2021-01-01T00:00:00Z (Unix timestamp 1609459200)
FARCASTER_EPOCH_OFFSET = 1609459200


def farcaster_time_to_datetime(farcaster_seconds: int | float | None) -> datetime:
    """将 Farcaster Epoch 秒数转换为标准 UTC datetime。"""
    if farcaster_seconds is None:
        return datetime.now(UTC)
    try:
        return datetime.fromtimestamp(FARCASTER_EPOCH_OFFSET + farcaster_seconds, tz=UTC)
    except (ValueError, OSError):
        return datetime.now(UTC)


class FarcasterCollector(DataCollector):
    """Farcaster 公开 Hub 内容采集器（Hubble HTTP API，零成本免 Key）。"""

    def __init__(self) -> None:
        super().__init__(source_id="farcaster", source_name="Farcaster")
        self.hub_url = settings.farcaster_hub_url.rstrip("/")
        self.timeout = settings.farcaster_timeout
        self.retry = settings.farcaster_retry
        self.channels = self._load_channels()
        self.rate_limiter = TokenBucketRateLimiter("farcaster")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.farcaster_enabled)

    def _load_channels(self) -> list[str]:
        raw = settings.farcaster_channels
        channels = [c.strip().lstrip("/") for c in raw.split(",") if c.strip()]
        return channels or ["airdrop", "airdrops", "testnet"]

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            items = await self._fetch_items()
            self.logger.info("farcaster.fetched", channel_count=len(self.channels), item_count=len(items))

            for item in items:
                discovery = self._build_discovery(item)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("farcaster.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_items(self) -> list[dict[str, Any]]:
        """逐频道查询公共 Hubble 节点的 castsByParent，任一失败只跳过该频道。"""
        items: list[dict[str, Any]] = []
        succeeded = 0
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for channel in self.channels:
                parent_url = f"https://farcaster.xyz/~/channel/{channel}"
                query_url = f"{self.hub_url}/v1/castsByParent?url={parent_url}&pageSize=25&reverse=1"
                try:
                    assert_url_allowed(query_url)
                    async with self.rate_limiter:
                        response = await client.get(query_url)
                        response.raise_for_status()

                    payload = response.json()
                    messages = payload.get("messages", [])
                    for msg in messages:
                        cast_data = msg.get("data", {})
                        body = cast_data.get("castAddBody", {})
                        text = body.get("text", "")
                        if not text.strip():
                            continue
                        cast_hash = msg.get("hash", "")
                        items.append(
                            {
                                "channel": channel,
                                "hash": cast_hash,
                                "fid": cast_data.get("fid"),
                                "timestamp": cast_data.get("timestamp"),
                                "text": text,
                                "embeds": body.get("embeds", []),
                            }
                        )
                    succeeded += 1
                except Exception as e:
                    last_error = e
                    self.logger.warning("farcaster.channel_failed", channel=channel, error=str(e))
                    continue

        if succeeded == 0 and last_error is not None:
            raise last_error

        return items

    def _build_discovery(self, item: dict[str, Any]) -> RawDiscovery | None:
        content = item.get("text") or ""
        if not content.strip():
            return None

        signal_type, signal_label = detect_signal(content)
        if signal_type is None:
            return None

        # 从正文或 embeds 中提取候选项目名
        name = extract_name(content)
        if not name:
            for embed in item.get("embeds", []):
                embed_url = embed.get("url") if isinstance(embed, dict) else str(embed)
                if embed_url:
                    name = extract_name(embed_url)
                    if name:
                        break
        name = name or "Unknown"

        channel = item.get("channel") or ""
        cast_hash = str(item.get("hash") or "")
        post_url = f"https://warpcast.com/~/conversations/{cast_hash}" if cast_hash else None
        dt = farcaster_time_to_datetime(item.get("timestamp"))

        raw_data = {
            "channel": channel,
            "hash": cast_hash,
            "fid": item.get("fid"),
            "text": content,
            "timestamp": dt.isoformat(),
            "signal_type": signal_type,
            "signal_label": signal_label,
            "embeds": item.get("embeds", []),
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={
                    "channel": channel,
                    "signal_type": signal_type,
                    "cast_hash": cast_hash,
                    "text_preview": content[:200],
                },
                signal_strength=0.5,
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=f"fc-{cast_hash}" if cast_hash else f"fc-{dt.timestamp()}",
            name=name,
            url=post_url,
            sector=None,
            stage="ideation",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=self._score(signal_type),
            discovered_at=dt,
        )

    @staticmethod
    def _score(signal_type: str) -> float:
        type_map = {
            "funding": 0.13,
            "tge": 0.11,
            "testnet": 0.10,
            "points": 0.08,
            "airdrop": 0.06,
        }
        score = type_map.get(signal_type, 0.05)
        return min(score, MAX_DISCOVERY_SCORE)
