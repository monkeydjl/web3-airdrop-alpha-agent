"""Rate Limiter for External Data Sources.

为不同外部数据源提供令牌桶式速率限制，防止触发源站限流或超额计费。

参考：
- DATA_SOURCE_STRATEGY.md §速率限制
- SECURITY.md §外部源访问
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import ClassVar

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class RateLimitConfig:
    """单个数据源的限流配置。"""

    requests_per_second: float = 1.0
    burst: int = 5
    daily_limit: int | None = None  # None 表示不限制


class TokenBucketRateLimiter:
    """异步令牌桶限流器。

    用法：
        limiter = TokenBucketRateLimiter("defillama", RateLimitConfig(2.0, 5))
        async with limiter:
            response = await client.get(url)
    """

    # 默认各源限流配置（可根据文档持续调整）
    DEFAULTS: ClassVar[dict[str, RateLimitConfig]] = {
        "defillama": RateLimitConfig(requests_per_second=2.0, burst=5),
        "github": RateLimitConfig(requests_per_second=1.0, burst=3),
        "coingecko": RateLimitConfig(requests_per_second=0.5, burst=2, daily_limit=10000),
        "twitter": RateLimitConfig(requests_per_second=0.2, burst=1),
        # Twitter 采集器用 twitter_kol / twitter_keyword 作为 source_id，
        # 需显式登记，否则回落到默认 1.0rps/burst5，比预期宽松 5 倍触发 429。
        "twitter_kol": RateLimitConfig(requests_per_second=0.2, burst=1),
        "twitter_keyword": RateLimitConfig(requests_per_second=0.2, burst=1),
        "cryptorank": RateLimitConfig(requests_per_second=1.0, burst=3),
        "rootdata": RateLimitConfig(requests_per_second=0.8, burst=2),
        "etherscan": RateLimitConfig(requests_per_second=0.2, burst=2),
        "galxe": RateLimitConfig(requests_per_second=0.5, burst=2),
        "layer3": RateLimitConfig(requests_per_second=0.5, burst=2),
    }

    def __init__(self, source_id: str, config: RateLimitConfig | None = None) -> None:
        self.source_id = source_id
        self.config = config or self.DEFAULTS.get(source_id, RateLimitConfig())
        self._tokens = float(self.config.burst)
        self._last_update = time.monotonic()
        self._lock = asyncio.Lock()
        self._daily_count = 0
        self._daily_epoch = self._utc_day()
        self._logger = logger.bind(source_id=source_id)

    @staticmethod
    def _utc_day() -> int:
        """当前 UTC 自然日序号（用于每日配额滚动重置）。"""
        return int(time.time() // 86400)

    async def acquire(self) -> None:
        """获取一个令牌，如无可用则等待。"""
        async with self._lock:
            # 跨自然日则重置每日计数，避免 daily_limit 变成进程生命周期内的永久锁定
            today = self._utc_day()
            if today != self._daily_epoch:
                self._daily_epoch = today
                self._daily_count = 0

            if self.config.daily_limit and self._daily_count >= self.config.daily_limit:
                self._logger.warning(
                    "rate_limit.daily_exceeded",
                    daily_limit=self.config.daily_limit,
                )
                raise RateLimitExceededError(f"{self.source_id} daily limit {self.config.daily_limit} exceeded")

            now = time.monotonic()
            elapsed = now - self._last_update
            self._tokens = min(
                self.config.burst,
                self._tokens + elapsed * self.config.requests_per_second,
            )
            self._last_update = now

            if self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self.config.requests_per_second
                self._logger.debug("rate_limit.wait", wait_seconds=wait)
                await asyncio.sleep(wait)
                self._tokens = 0.0
                self._last_update = time.monotonic()
            else:
                self._tokens -= 1.0

            self._daily_count += 1

    async def __aenter__(self) -> TokenBucketRateLimiter:
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class RateLimitExceededError(Exception):
    """超出限流配额。"""

    pass
