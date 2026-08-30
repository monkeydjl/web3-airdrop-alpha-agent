"""Medium Collector.

从 Medium 的公开 RSS tag feed 采集早期项目信号（路线图 / 公告 / 创作内容）。
Medium RSS 无需 Key。

参考：
- DATA_SOURCE_STRATEGY.md §2（P2 源）
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import defusedxml.ElementTree as ET  # noqa: N817 — defusedxml 防 XML 攻击（SECURITY 相关）
import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.content_signals import detect_signal, extract_name
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings

logger = structlog.get_logger(__name__)

# 内容源是二阶信号（内容里"提到"项目），不是项目目录：discovery_score 上限
# 刻意压在分析阈值 0.3 以下，只贡献 project_signals，不触发 LLM 分析（§5.4）。
MAX_DISCOVERY_SCORE = 0.28


class MediumCollector(DataCollector):
    """Medium 内容采集器（RSS tag feed，免费）。"""

    def __init__(self) -> None:
        super().__init__(source_id="medium", source_name="Medium")
        self.timeout = settings.medium_timeout
        self.retry = settings.medium_retry
        self.tags = self._load_tags()
        self.rate_limiter = TokenBucketRateLimiter("medium")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.medium_enabled)

    def _load_tags(self) -> list[str]:
        raw = settings.medium_tags
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        return tags or ["airdrop"]

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            items = await self._fetch_items()
            self.logger.info("medium.fetched", tag_count=len(self.tags), item_count=len(items))

            for item in items:
                discovery = self._build_discovery(item)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("medium.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_items(self) -> list[dict[str, Any]]:
        """逐 tag 抓取 RSS，任一 tag 失败只丢该 tag，全失败才向上抛。"""
        items: list[dict[str, Any]] = []
        succeeded = 0
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for tag in self.tags:
                url = f"https://medium.com/feed/tag/{tag}"
                try:
                    async with self.rate_limiter:
                        response = await client.get(url)
                        response.raise_for_status()
                    items.extend(self._parse_rss(response.text, tag))
                    succeeded += 1
                except Exception as e:
                    last_error = e
                    self.logger.warning("medium.tag_failed", tag=tag, error=str(e))
                    continue
        if succeeded == 0 and last_error is not None:
            raise last_error
        return items

    @staticmethod
    def _parse_rss(xml_text: str, tag: str) -> list[dict[str, Any]]:
        root = ET.fromstring(xml_text)
        parsed: list[dict[str, Any]] = []
        for item_el in root.iter("item"):
            title = (item_el.findtext("title") or "").strip()
            link = (item_el.findtext("link") or "").strip()
            description = (item_el.findtext("description") or "").strip()
            creator = (item_el.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()
            pub_date = (item_el.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            parsed.append(
                {
                    "title": title,
                    "link": link,
                    "description": description,
                    "creator": creator,
                    "pub_date": pub_date,
                    "tag": tag,
                }
            )
        return parsed

    def _build_discovery(self, item: dict[str, Any]) -> RawDiscovery | None:
        title = item["title"]
        text = f"{title} {item.get('description', '')}"
        signal_type, signal_label = detect_signal(text)
        if signal_type is None:
            return None

        name = extract_name(f"{title} {item.get('link', '')}") or "Unknown"
        link = item.get("link") or None

        raw_data = {
            "title": title,
            "link": link,
            "creator": item.get("creator"),
            "pub_date": item.get("pub_date"),
            "tag": item.get("tag"),
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"title": title, "tag": item.get("tag"), "signal_type": signal_type},
                signal_strength=0.4,
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=link or f"medium-{datetime.now(UTC).timestamp()}",
            name=name,
            url=link,
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
                response = await client.get(f"https://medium.com/feed/tag/{self.tags[0]}")
                response.raise_for_status()
            return {"source_id": self.source_id, "status": "healthy"}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}
