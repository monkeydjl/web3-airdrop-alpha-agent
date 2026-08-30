"""Reddit Collector.

通过 Reddit OAuth（script app）搜索社区提及，采集社区情绪类早期信号。

参考：
- DATA_SOURCE_STRATEGY.md §2（P2 源）
"""

from __future__ import annotations

import base64
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

OAUTH_ENDPOINT = "https://www.reddit.com/api/v1/access_token"
SEARCH_URL = "https://oauth.reddit.com/search.json"

SEARCH_TERMS = [
    "airdrop",
    'subreddit:CryptoAirdrops "no token"',
    "subreddit:CryptoAirdrops testnet",
]


class RedditCollector(DataCollector):
    """Reddit 社区情绪采集器（OAuth，需 client_id/secret + username）。"""

    MAX_RESULTS = 25

    def __init__(self) -> None:
        super().__init__(source_id="reddit", source_name="Reddit")
        self.client_id = settings.reddit_client_id
        self.client_secret = settings.reddit_client_secret
        self.username = settings.reddit_username
        self.user_agent = settings.reddit_user_agent
        self.timeout = settings.reddit_timeout
        self.retry = settings.reddit_retry
        self.rate_limiter = TokenBucketRateLimiter("reddit")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.reddit_enabled and self.client_id and self.client_secret and self.username)

    def _auth_header(self) -> dict[str, str]:
        raw = f"{self.client_id}:{self.client_secret}".encode()
        token = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {token}"}

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            access_token = await self._fetch_access_token()
            posts = await self._search_all(access_token)
            self.logger.info("reddit.fetched", term_count=len(SEARCH_TERMS), post_count=len(posts))

            for post in posts:
                discovery = self._build_discovery(post)
                if discovery is not None:
                    result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("reddit.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_access_token(self) -> str:
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                OAUTH_ENDPOINT,
                headers=self._auth_header(),
                data={"grant_type": "client_credentials"},
            )
            response.raise_for_status()
            data = response.json()
        token = data.get("access_token")
        if not token:
            raise ValueError(f"Reddit OAuth 无 access_token：{data}")
        return str(token)

    async def _search_all(self, access_token: str) -> list[dict[str, Any]]:
        posts: list[dict[str, Any]] = []
        succeeded = 0
        last_error: Exception | None = None
        headers = {"Authorization": f"Bearer {access_token}", "User-Agent": self.user_agent}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for term in SEARCH_TERMS:
                try:
                    async with self.rate_limiter:
                        response = await client.get(
                            SEARCH_URL,
                            params={"q": term, "sort": "new", "limit": self.MAX_RESULTS},
                            headers=headers,
                        )
                        response.raise_for_status()
                    posts.extend(self._parse_search(response.json()))
                    succeeded += 1
                except Exception as e:
                    last_error = e
                    self.logger.warning("reddit.term_failed", term=term, error=str(e))
                    continue
        if succeeded == 0 and last_error is not None:
            raise last_error
        return posts

    @staticmethod
    def _parse_search(data: dict[str, Any]) -> list[dict[str, Any]]:
        children = ((data.get("data") or {}).get("children")) or []
        out: list[dict[str, Any]] = []
        for child in children:
            post = child.get("data") or {}
            if post.get("title"):
                out.append(post)
        return out

    def _build_discovery(self, post: dict[str, Any]) -> RawDiscovery | None:
        title = post.get("title") or ""
        selftext = post.get("selftext") or ""
        text = f"{title} {selftext}"

        signal_type, signal_label = detect_signal(text)
        if signal_type is None:
            return None

        name = extract_name(f"{title} {post.get('url', '')}") or f"r/{post.get('subreddit', 'unknown')}"
        post_id = post.get("id") or ""
        permalink = post.get("permalink") or ""
        url = f"https://reddit.com{permalink}" if permalink else None

        raw_data = {
            "reddit_id": post_id,
            "title": title,
            "subreddit": post.get("subreddit"),
            "score": post.get("score"),
            "num_comments": post.get("num_comments"),
            "created_utc": post.get("created_utc"),
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="community_activity",
                signal_source=self.source_id,
                signal_data={"subreddit": post.get("subreddit"), "signal_type": signal_type},
                signal_strength=self._engagement_strength(post.get("score") or 0, post.get("num_comments") or 0),
            )
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=post_id or f"reddit-{datetime.now(UTC).timestamp()}",
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
    def _engagement_strength(score: int, comments: int) -> float:
        return round(min(1.0, score / 500) * 0.7 + min(1.0, comments / 100) * 0.3, 4)

    @staticmethod
    def _score(signal_type: str) -> float:
        type_map = {"funding": 0.13, "tge": 0.11, "testnet": 0.10, "points": 0.08, "airdrop": 0.06}
        return round(min(MAX_DISCOVERY_SCORE, 0.15 + type_map.get(signal_type, 0.05)), 4)

    async def health_check(self) -> dict[str, Any]:
        if not self.is_enabled():
            return {"source_id": self.source_id, "status": "disabled"}
        try:
            access_token = await self._fetch_access_token()
            return {"source_id": self.source_id, "status": "healthy", "token": bool(access_token)}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": str(e)}
