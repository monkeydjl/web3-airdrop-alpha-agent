"""Twitter/X Collector.

从 Twitter/X API v2 采集早期项目信号：
- KOL/VC 账号监听（融资、测试网、积分计划公告）
- 关键词搜索（#airdrop #testnet #points 等）

参考：
- DATA_SOURCE_STRATEGY.md §4. Twitter/X
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings

logger = structlog.get_logger(__name__)


# 默认监听账号（DATA_SOURCE_STRATEGY.md 推荐）
DEFAULT_KOL_ACCOUNTS = [
    "a16z",
    "paradigm",
    "VitalikButerin",
    "cz_binance",
    "BinanceLabs",
    "coinbase",
    "panteracapital",
    "dragonfly_xyz",
    "polychaincap",
    "1kxnetwork",
]

# 默认关键词
DEFAULT_KEYWORDS = [
    "#airdrop",
    "#testnet",
    "#points",
    "#mainnet",
    "points program",
    "no token yet",
    "TGE soon",
]

# 信号关键词 → 信号类型
SIGNAL_KEYWORDS = {
    "testnet": "testnet",
    "mainnet": "mainnet",
    "points": "points",
    "airdrop": "airdrop",
    "funding": "funding",
    "raised": "funding",
    "invest": "funding",
    "tge": "tge",
    "launch": "launch",
}


class TwitterCollector(DataCollector):
    """Twitter/X 采集器基类。

    子类需实现 collect() 中的具体采集策略（KOL/关键词）。
    """

    MAX_RESULTS = 50
    SOURCE_TYPE = "api"

    def __init__(self, source_id: str, source_name: str) -> None:
        super().__init__(source_id=source_id, source_name=source_name)
        self.base_url = "https://api.twitter.com/2"
        self.bearer_token = settings.twitter_bearer_token
        self.timeout = getattr(settings, "twitter_timeout", 30)
        self.retry = getattr(settings, "twitter_retry", 3)
        self.rate_limiter = TokenBucketRateLimiter(source_id)
        self.logger = logger.bind(source_id=source_id)

    @property
    def source_type(self) -> str:
        return self.SOURCE_TYPE

    def is_enabled(self) -> bool:
        # 必须同时开启开关且配置 Bearer Token
        return settings.twitter_enabled and bool(self.bearer_token)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.bearer_token}"}

    def _search_params(self, query: str, max_results: int | None = None) -> dict[str, Any]:
        """构造 search/recent 的公共参数。"""
        return {
            "query": query,
            "max_results": max_results or self.MAX_RESULTS,
            "tweet.fields": "created_at,public_metrics,author_id,lang",
        }

    @asynccontextmanager
    async def _http_client(self, client: httpx.AsyncClient | None = None):
        """复用调用方传入的客户端，否则临时自建一个。

        批量查询（KOL 分批 / 多关键词）传入同一客户端即可跨请求复用连接，
        省掉每轮搜索一次 TCP+TLS 握手。
        """
        if client is not None:
            yield client
        else:
            async with httpx.AsyncClient(timeout=self.timeout) as owned:
                yield owned

    async def _search_recent(
        self,
        query: str,
        max_results: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> list[dict[str, Any]]:
        """调用 Twitter API v2 search/recent。"""
        url = f"{self.base_url}/tweets/search/recent"
        params = self._search_params(query, max_results)

        async with self._http_client(client) as http, self.rate_limiter:
            response = await http.get(url, params=params, headers=self._headers())
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected Twitter response type: {type(data)}")

        return data.get("data", [])

    def _extract_project_signals(self, tweets: list[dict[str, Any]]) -> list[RawDiscovery]:
        """从推文列表中提取项目信号，生成 RawDiscovery。"""
        discoveries: list[RawDiscovery] = []
        for tweet in tweets:
            discovery = self._build_discovery(tweet)
            if discovery:
                discoveries.append(discovery)
        return discoveries

    def _build_discovery(self, tweet: dict[str, Any]) -> RawDiscovery | None:
        """将单条推文转换为 RawDiscovery（若检测到项目信号）。"""
        text = tweet.get("text", "")
        if not text:
            return None

        signal_type, signal_label = self._detect_signal_type(text)
        if not signal_type:
            # 没有明确信号关键词，跳过
            return None

        project_name = self._extract_project_name(text) or "Unknown"
        public_metrics = tweet.get("public_metrics", {}) or {}
        like_count = public_metrics.get("like_count", 0) or 0
        retweet_count = public_metrics.get("retweet_count", 0) or 0
        reply_count = public_metrics.get("reply_count", 0) or 0
        author_id = tweet.get("author_id", "")
        tweet_id = tweet.get("id", "")
        created_at = tweet.get("created_at", datetime.now(UTC).isoformat())

        # 推文 URL 作为项目来源页
        tweet_url = f"https://twitter.com/i/web/status/{tweet_id}" if tweet_id else None

        raw_data = {
            "tweet_id": tweet_id,
            "author_id": author_id,
            "text": text,
            "created_at": created_at,
            "like_count": like_count,
            "retweet_count": retweet_count,
            "reply_count": reply_count,
            "quote_count": public_metrics.get("quote_count", 0) or 0,
            "lang": tweet.get("lang"),
            "signal_type": signal_type,
            "signal_label": signal_label,
        }

        signals = [
            RawSignal(
                signal_type="twitter_mention",
                signal_source="twitter",
                signal_data={
                    "tweet_id": tweet_id,
                    "author_id": author_id,
                    "text": text,
                    "like_count": like_count,
                    "retweet_count": retweet_count,
                    "signal_type": signal_type,
                    "signal_label": signal_label,
                },
                signal_strength=self._calculate_engagement_strength(like_count, retweet_count, reply_count),
            ),
        ]

        discovery_score = self._calculate_discovery_score(
            signal_type, like_count, retweet_count, reply_count, self.source_id
        )

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=tweet_id or f"twitter-{datetime.now(UTC).timestamp()}",
            name=project_name,
            url=tweet_url,
            # 推文不掌握赛道；显式留空而非归一化成 "Unknown" 占位
            sector=None,
            stage="ideation",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _detect_signal_type(self, text: str) -> tuple[str | None, str | None]:
        """检测推文中的信号类型与命中词。"""
        lower_text = text.lower()
        for keyword, signal_type in SIGNAL_KEYWORDS.items():
            if keyword in lower_text:
                return signal_type, keyword
        return None, None

    def _extract_project_name(self, text: str) -> str | None:
        """从推文中提取潜在项目名（启发式）。

        优先级：
        1. URL 主域名（过滤常见域名）
        2. CamelCase 词（更可能是项目名）
        3. 普通首字母大写词（排除常见句子词）
        4. @handle（排除知名 KOL 账号）
        """
        # 1. 尝试从 URL 域名中提取
        url_match = re.search(r"https?://(?:www\.)?([^/\s]+)", text)
        if url_match:
            domain = url_match.group(1).lower()
            # 过滤常见域名
            if domain not in {"t.co", "twitter.com", "x.com", "youtu.be", "youtube.com"}:
                # 取主域名第一部分
                parts = domain.split(".")
                if len(parts) >= 2:
                    candidate = parts[-2]
                    if len(candidate) >= 3:
                        return candidate.capitalize()

        # 2. 优先匹配 CamelCase / PascalCase 项目名（如 NovaLayer, AuroraDex）
        camel_words = re.findall(r"\b[A-Z][a-z]+[A-Z][a-zA-Z0-9]+\b", text)
        for word in camel_words:
            if word not in self.STOP_WORDS:
                return word

        # 3. 普通首字母大写词，排除常见非项目词
        words = re.findall(r"\b[A-Z][a-zA-Z0-9]{2,}\b", text)
        for word in words:
            if word not in self.STOP_WORDS:
                return word

        # 4. 从 @handle 中提取（非知名账号）
        handles = re.findall(r"@([A-Za-z0-9_]{3,})", text)
        for handle in handles:
            if handle.lower() not in {a.lower() for a in DEFAULT_KOL_ACCOUNTS}:
                return handle.capitalize()

        return None

    # 常见句子开头词/情感词, 不应作为项目名
    STOP_WORDS: ClassVar[set[str]] = {
        "The",
        "This",
        "That",
        "New",
        "Big",
        "Web",
        "Crypto",
        "Blockchain",
        "Bitcoin",
        "Ethereum",
        "Here",
        "What",
        "When",
        "Where",
        "How",
        "Why",
        "Airdrop",
        "Testnet",
        "Points",
        "Mainnet",
        "Token",
        "Launch",
        "Today",
        "Just",
        "Now",
        "First",
        "Next",
        "Last",
        "Year",
        "Month",
        "Week",
        "Day",
        "Excited",
        "Happy",
        "Thrilled",
        "Proud",
        "Announcing",
        "Announced",
        "We",
        "Our",
        "Us",
        "They",
        "Their",
        "He",
        "She",
        "It",
        "Its",
        "You",
        "Your",
        "Have",
        "Has",
        "Had",
        "Are",
        "Is",
        "Was",
        "Were",
        "Get",
        "Got",
        "Goes",
        "Going",
        "Come",
        "Came",
        "Can",
        "Could",
        "Will",
        "Would",
        "Should",
        "May",
        "Might",
        "Must",
        "Shall",
        "Make",
        "Made",
        "Take",
        "Took",
        "Give",
        "Gave",
        "See",
        "Saw",
        "Want",
        "Wanted",
        "Need",
        "Needed",
        "Like",
        "Liked",
        "Love",
        "Loved",
        "Think",
        "Thought",
        "Know",
        "Knew",
        "Use",
        "Used",
        "Work",
        "Worked",
        "Help",
        "Helped",
        "Try",
        "Tried",
        "Start",
        "Started",
        "Stop",
        "Stopped",
    }

    def _calculate_engagement_strength(
        self,
        likes: int,
        retweets: int,
        replies: int,
    ) -> float:
        """根据互动量计算信号强度 0-1。"""
        like_score = min(1.0, likes / 1000)
        retweet_score = min(1.0, retweets / 500)
        reply_score = min(1.0, replies / 100)
        return round(like_score * 0.4 + retweet_score * 0.4 + reply_score * 0.2, 4)

    def _calculate_discovery_score(
        self,
        signal_type: str,
        likes: int,
        retweets: int,
        replies: int,
        source_id: str,
    ) -> float:
        """计算 Twitter 发现质量分。

        - 来源权重：KOL 监听 > 关键词搜索
        - 信号类型：funding/testnet/points > 泛化关键词
        - 互动量：越高越好
        """
        source_weight = 0.3 if source_id == "twitter_kol" else 0.1

        type_weight_map = {
            "funding": 0.35,
            "testnet": 0.30,
            "points": 0.25,
            "airdrop": 0.20,
            "tge": 0.20,
            "mainnet": 0.15,
            "launch": 0.15,
        }
        type_weight = type_weight_map.get(signal_type, 0.1)

        engagement = self._calculate_engagement_strength(likes, retweets, replies)

        score = source_weight + type_weight + engagement * 0.25
        return round(min(1.0, score), 4)

    async def health_check(self) -> dict[str, Any]:
        """检查 Twitter API 可用性（调用 search/recent 配额检查）。"""
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/tweets/search/recent",
                    params={"query": "airdrop", "max_results": 10},
                    headers=self._headers(),
                )
                response.raise_for_status()
                data = response.json()
                return {
                    "source_id": self.source_id,
                    "status": "healthy",
                    "tweet_count": len(data.get("data", [])),
                }
        except Exception as e:
            return {
                "source_id": self.source_id,
                "status": "unhealthy",
                "error": str(e),
            }


class TwitterKolCollector(TwitterCollector):
    """监听 KOL/VC 账号的 Twitter 采集器。"""

    def __init__(self) -> None:
        super().__init__(source_id="twitter_kol", source_name="Twitter KOL/VC")
        self.accounts = self._load_accounts()

    def _load_accounts(self) -> list[str]:
        """加载监听账号列表，支持环境变量覆盖。"""
        raw = getattr(settings, "twitter_kol_accounts", "")
        if raw:
            return [a.strip() for a in raw.split(",") if a.strip()]
        return DEFAULT_KOL_ACCOUNTS

    async def collect(self) -> CollectorResult:
        """执行 KOL/VC 账号监听采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            tweets = await self._fetch_kol_tweets()
            self.logger.info(
                "twitter_kol.fetched",
                total_tweets=len(tweets),
            )

            discoveries = self._extract_project_signals(tweets)
            for discovery in discoveries:
                result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("twitter_kol.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_kol_tweets(self) -> list[dict[str, Any]]:
        """获取监听账号的近期推文。

        使用 search/recent 的 from:handle 操作符，分批查询以避免超长 query。
        """
        all_tweets: list[dict[str, Any]] = []
        # 每批 5 个账号，控制 query 长度
        batch_size = 5
        # 整轮共用一个客户端复用连接；单批失败只丢该批，已取回的推文照常保留。
        # 但若所有批次都失败，说明是鉴权/限流等整体故障，向上抛出标记为 error。
        succeeded = 0
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for i in range(0, len(self.accounts), batch_size):
                batch = self.accounts[i : i + batch_size]
                # from:handle OR from:handle ... -is:retweet
                handles = " OR ".join(f"from:{handle}" for handle in batch)
                query = f"({handles}) -is:retweet"
                try:
                    tweets = await self._search_recent(query, max_results=50, client=client)
                except Exception as e:
                    last_error = e
                    self.logger.warning("twitter_kol.batch_failed", batch_index=i, error=str(e))
                    continue
                succeeded += 1
                all_tweets.extend(tweets)
        if succeeded == 0 and last_error is not None:
            raise last_error
        return all_tweets


class TwitterKeywordCollector(TwitterCollector):
    """按关键词搜索 Twitter 的采集器。"""

    def __init__(self) -> None:
        super().__init__(source_id="twitter_keyword", source_name="Twitter Keywords")
        self.keywords = self._load_keywords()

    def _load_keywords(self) -> list[str]:
        """加载关键词列表，支持环境变量覆盖。"""
        raw = getattr(settings, "twitter_keywords", "")
        if raw:
            return [k.strip() for k in raw.split(",") if k.strip()]
        return DEFAULT_KEYWORDS

    async def collect(self) -> CollectorResult:
        """执行关键词搜索采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            tweets = await self._fetch_keyword_tweets()
            self.logger.info(
                "twitter_keyword.fetched",
                total_tweets=len(tweets),
            )

            discoveries = self._extract_project_signals(tweets)
            for discovery in discoveries:
                result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("twitter_keyword.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_keyword_tweets(self) -> list[dict[str, Any]]:
        """获取关键词搜索结果。"""
        all_tweets: list[dict[str, Any]] = []
        # 每个关键词单独查询，便于归因与限流控制；整轮共用一个客户端复用连接。
        # 单个关键词失败不影响其余；全部失败则向上抛出以标记整轮 error。
        succeeded = 0
        last_error: Exception | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for keyword in self.keywords:
                query = f"{keyword} -is:retweet"
                try:
                    tweets = await self._search_recent(query, max_results=25, client=client)
                except Exception as e:
                    last_error = e
                    self.logger.warning("twitter_keyword.query_failed", keyword=keyword, error=str(e))
                    continue
                succeeded += 1
                all_tweets.extend(tweets)
        if succeeded == 0 and last_error is not None:
            raise last_error
        return all_tweets


if __name__ == "__main__":
    import asyncio

    async def main():
        kol = TwitterKolCollector()
        keyword = TwitterKeywordCollector()
        for collector in (kol, keyword):
            if not collector.is_enabled():
                print(f"{collector.source_id} disabled")
                continue
            result = await collector.collect()
            print(f"{collector.source_id}: {result.status}, {len(result.items)} items")
            for item in result.items[:5]:
                print(f"  - {item.name} ({item.discovery_score})")

    asyncio.run(main())
