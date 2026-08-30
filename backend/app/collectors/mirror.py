"""Mirror Collector.

通过 Arweave GraphQL（公开、免费）查询 Mirror 上链文章
（App-Name: Mirror 的交易），采集路线图 / 公告类早期信号。

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

ARWEAVE_GRAPHQL_URL = "https://arweave.net/graphql"
MIRROR_QUERY = """
query MirrorArticles($first: Int!) {
  transactions(
    tags: [{ name: "App-Name", values: ["Mirror"] }],
    first: $first,
    sort: HEIGHT_DESC
  ) {
    edges {
      node {
        id
        tags { name value }
      }
    }
  }
}
""".strip()


class MirrorCollector(DataCollector):
    """Mirror 内容采集器（Arweave 公开读，无需 Key）。"""

    MAX_ARTICLES = 50

    def __init__(self) -> None:
        super().__init__(source_id="mirror", source_name="Mirror")
        self.timeout = settings.mirror_timeout
        self.retry = settings.mirror_retry
        self.rate_limiter = TokenBucketRateLimiter("mirror")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.mirror_enabled)

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            articles = await self._fetch_articles()
            self.logger.info("mirror.fetched", article_count=len(articles))

            for article in articles:
                discovery = self._build_discovery(article)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("mirror.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_articles(self) -> list[dict[str, Any]]:
        payload = {"query": MIRROR_QUERY, "variables": {"first": self.MAX_ARTICLES}}
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(ARWEAVE_GRAPHQL_URL, json=payload)
            response.raise_for_status()
            data = response.json()

        if "errors" in data:
            raise ValueError(f"Arweave GraphQL error: {data['errors']}")

        edges = ((data.get("data") or {}).get("transactions") or {}).get("edges") or []
        articles: list[dict[str, Any]] = []
        for edge in edges:
            node = edge.get("node") or {}
            tags = node.get("tags") or []
            tag_map: dict[str, str] = {}
            for tag in tags:
                name = (tag.get("name") or "").strip()
                value = (tag.get("value") or "").strip()
                if name and value:
                    tag_map[name] = value
            articles.append(
                {
                    "tx_id": node.get("id") or "",
                    "title": tag_map.get("Title", ""),
                    "contributor": tag_map.get("Contributor", ""),
                }
            )
        return articles

    def _build_discovery(self, article: dict[str, Any]) -> RawDiscovery | None:
        title = article.get("title") or ""
        if not title:
            return None

        signal_type, signal_label = detect_signal(title)
        if signal_type is None:
            return None

        name = extract_name(title) or "Unknown"
        contributor = article.get("contributor") or ""
        tx_id = article.get("tx_id") or ""
        url = f"https://mirror.xyz/{contributor}/{tx_id}" if contributor and tx_id else None

        raw_data = {
            "tx_id": tx_id,
            "title": title,
            "contributor": contributor,
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"title": title, "contributor": contributor, "signal_type": signal_type},
                signal_strength=0.4,
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=tx_id or f"mirror-{datetime.now(UTC).timestamp()}",
            name=name,
            url=url,
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
                response = await client.post(
                    ARWEAVE_GRAPHQL_URL,
                    json={"query": MIRROR_QUERY, "variables": {"first": 1}},
                )
                response.raise_for_status()
            return {"source_id": self.source_id, "status": "healthy"}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}
