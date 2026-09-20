"""Telegram Channel Collector.

从 Telegram 公开频道的 Web 预览页面（https://t.me/s/{channel}）采集早期项目空投/Alpha 信号。
完全免费，无需 API Key、无需手机号登录或 Bot Token。

参考：
- DATA_SOURCE_STRATEGY.md §2（P2 源）
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from html.parser import HTMLParser
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


class TelegramWebParser(HTMLParser):
    """解析 https://t.me/s/{channel} 公开频道预览网页 HTML。"""

    def __init__(self, channel: str) -> None:
        super().__init__()
        self.channel = channel
        self.messages: list[dict[str, Any]] = []
        self._current_post_id: str | None = None
        self._current_datetime: str | None = None
        self._current_url: str | None = None
        self._text_depth = 0
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)

        # 消息外层容器：获取 post_id
        if tag == "div" and "data-post" in attr_dict:
            post_attr = attr_dict.get("data-post") or ""
            if "/" in post_attr:
                self._current_post_id = post_attr.split("/")[-1]
            else:
                self._current_post_id = post_attr

        # 时间标签
        if tag == "time" and "datetime" in attr_dict:
            self._current_datetime = attr_dict.get("datetime")

        # 消息日期固定链接
        if tag == "a":
            classes = (attr_dict.get("class") or "").split()
            if "tgme_widget_message_date" in classes:
                self._current_url = attr_dict.get("href")

        # 消息正文容器
        if tag == "div":
            classes = (attr_dict.get("class") or "").split()
            if any("tgme_widget_message_text" in c for c in classes):
                self._text_depth = 1
                self._text_parts = []
            elif self._text_depth > 0:
                self._text_depth += 1
        elif tag == "br" and self._text_depth > 0:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._text_depth > 0:
            self._text_depth -= 1
            if self._text_depth == 0:
                text = "".join(self._text_parts).strip()
                if text and self._current_post_id:
                    self.messages.append(
                        {
                            "post_id": self._current_post_id,
                            "channel": self.channel,
                            "text": text,
                            "datetime": self._current_datetime,
                            "url": self._current_url or f"https://t.me/{self.channel}/{self._current_post_id}",
                        }
                    )
                self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._text_depth > 0:
            self._text_parts.append(data)


class TelegramChannelCollector(DataCollector):
    """Telegram 公开频道内容采集器（HTTP 网页预览，零成本免 Key）。"""

    def __init__(self) -> None:
        super().__init__(source_id="telegram", source_name="Telegram")
        self.timeout = settings.telegram_timeout
        self.retry = settings.telegram_retry
        self.channels = self._load_channels()
        self.rate_limiter = TokenBucketRateLimiter("telegram")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.telegram_enabled)

    def _load_channels(self) -> list[str]:
        raw = settings.telegram_channels
        channels = [c.strip().lstrip("@") for c in raw.split(",") if c.strip()]
        return channels or ["airdropinspect"]

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            items = await self._fetch_items()
            self.logger.info("telegram.fetched", channel_count=len(self.channels), item_count=len(items))

            for item in items:
                discovery = self._build_discovery(item)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("telegram.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_items(self) -> list[dict[str, Any]]:
        """逐频道抓取公共预览页面，任一频道失败只丢该频道，全失败才向上抛。"""
        items: list[dict[str, Any]] = []
        succeeded = 0
        last_error: Exception | None = None

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for channel in self.channels:
                url = f"https://t.me/s/{channel}"
                try:
                    assert_url_allowed(url)
                    async with self.rate_limiter:
                        response = await client.get(url)
                        response.raise_for_status()

                    parser = TelegramWebParser(channel)
                    parser.feed(response.text)
                    items.extend(parser.messages)
                    succeeded += 1
                except Exception as e:
                    last_error = e
                    self.logger.warning("telegram.channel_failed", channel=channel, error=str(e))
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

        name = extract_name(content) or "Unknown"
        channel = item.get("channel") or ""
        post_id = str(item.get("post_id") or "")
        post_url = item.get("url") or (f"https://t.me/{channel}/{post_id}" if channel and post_id else None)

        raw_data = {
            "channel": channel,
            "post_id": post_id,
            "text": content,
            "timestamp": item.get("datetime"),
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={
                    "channel": channel,
                    "signal_type": signal_type,
                    "post_id": post_id,
                    "text_preview": content[:200],
                },
                signal_strength=0.5,
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=f"tg-{channel}-{post_id}" if channel and post_id else f"tg-{datetime.now(UTC).timestamp()}",
            name=name,
            url=post_url,
            sector=None,
            stage="ideation",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=self._score(signal_type),
            discovered_at=datetime.now(UTC),
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
