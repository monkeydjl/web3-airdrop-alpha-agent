"""HTTP Fetcher with caching, retry, circuit breaker, and concurrency control.

Provides unified HTTP client with:
- Two-tier cache: in-memory LRU + disk JSON cache (§10.1)
- Exponential backoff retry
- Sliding window circuit breaker (configurable via settings)
- asyncio.Semaphore concurrency gate (fetcher_semaphore_size)
- Prometheus metrics: cache hit/miss, semaphore usage, circuit breaker state

Reference:
- CONVENTIONS.md §14 错误处理
- ENGINEERING_ROADMAP.md §10 数据容错
- V2_TASKS.md B1
"""

import asyncio
import contextlib
import hashlib
import json
import time
from collections import deque
from pathlib import Path
from typing import Any, ClassVar, cast

import httpx
import structlog

from app.config import settings
from app.metrics import (
    FETCHER_CACHE_HITS,
    FETCHER_CACHE_MISSES,
    FETCHER_CIRCUIT_BREAKER_STATE,
    FETCHER_SEMAPHORE_USAGE,
)

logger = structlog.get_logger(__name__)


# ═══════════════════════════════════════════════════════════════
# Circuit Breaker
# ═══════════════════════════════════════════════════════════════


class CircuitBreaker:
    """Sliding window circuit breaker.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit tripped, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """

    _STATE_MAP: ClassVar[dict[str, int]] = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}

    def __init__(
        self,
        threshold: int | None = None,
        timeout: int | None = None,
        window_size: int = 100,
    ) -> None:
        self.threshold = threshold or settings.fetcher_circuit_breaker_threshold
        self.timeout = timeout or settings.fetcher_circuit_breaker_timeout_seconds
        self.window_size = window_size

        self.failures: deque[float] = deque(maxlen=window_size)
        self.last_failure_time: float = 0
        self.state = "CLOSED"
        self._update_metric()

    def record_success(self) -> None:
        """Record successful request"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failures.clear()
            self._update_metric()
            logger.info("circuit_breaker.closed")

    def record_failure(self) -> None:
        """Record failed request"""
        self.failures.append(time.time())
        self.last_failure_time = time.time()

        # Count recent failures (within window)
        recent_failures = sum(1 for t in self.failures if time.time() - t < self.timeout)

        if recent_failures >= self.threshold and self.state != "OPEN":
            self.state = "OPEN"
            self._update_metric()
            logger.warning("circuit_breaker.opened", failures=recent_failures, threshold=self.threshold)

    def allow_request(self) -> bool:
        """Check if request should be allowed"""
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if timeout elapsed
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = "HALF_OPEN"
                self._update_metric()
                logger.info("circuit_breaker.half_open")
                return True
            return False

        # HALF_OPEN: allow one request to test
        return True

    def _update_metric(self) -> None:
        """Sync circuit breaker state to Prometheus gauge."""
        # 指标是 best-effort，但不能完全静默：suppress 保证不影响主流程，
        # debug 日志保留排查线路（指标注册表冲突等）。
        with contextlib.suppress(Exception):
            FETCHER_CIRCUIT_BREAKER_STATE.set(self._STATE_MAP.get(self.state, 0))


# ═══════════════════════════════════════════════════════════════
# Two-tier Cache (in-memory + disk)
# ═══════════════════════════════════════════════════════════════


class HTTPCache:
    """Two-tier cache: in-memory LRU + disk JSON files.

    Memory tier is always active. Disk tier activates when
    settings.fetcher_cache_dir is non-empty.
    """

    def __init__(self, max_size: int = 1000, cache_dir: str | None = None) -> None:
        self._cache: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)

    def _disk_path(self, key: str) -> Path | None:
        """Return disk cache file path for key, or None if disk disabled."""
        if not self._cache_dir:
            return None
        key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._cache_dir / f"{key_hash}.json"

    def get(self, key: str, ttl: int) -> Any | None:
        """Get cached value if not expired (checks memory then disk).

        `ttl <= 0` 表示"不使用缓存"，直接判定为已过期——不能靠比较时间算出来：
        原实现用 `age > ttl`，而 Windows 上 time.time() 分辨率约 15.6ms，同一时刻
        写入再读取时 age 就是 0.0，`0 > 0` 为 False，于是返回了本该过期的数据
        （实测 20 次里 14 次命中脏数据）。磁盘层更糟：文件 mtime 可能比
        time.time() 略微**超前**，age 变成负数，连 `age >= ttl` 也挡不住。
        """
        if ttl <= 0:
            self.invalidate(key)
            return None

        now = time.time()

        # 1. Memory tier
        if key in self._cache:
            value, timestamp = self._cache[key]
            if now - timestamp >= ttl:
                del self._cache[key]
            else:
                return value

        # 2. Disk tier
        disk_path = self._disk_path(key)
        if disk_path and disk_path.exists():
            try:
                mtime = disk_path.stat().st_mtime
                if now - mtime >= ttl:
                    disk_path.unlink(missing_ok=True)
                    return None
                with open(disk_path, encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                # Corrupt cache file — remove and fall through
                disk_path.unlink(missing_ok=True)

        return None

    def invalidate(self, key: str) -> None:
        """丢弃某个 key 的两层缓存（不存在时静默返回）。"""
        self._cache.pop(key, None)
        disk_path = self._disk_path(key)
        if disk_path:
            with contextlib.suppress(OSError):
                disk_path.unlink(missing_ok=True)

    def set(self, key: str, value: Any) -> None:
        """Set cached value in both tiers."""
        # Memory tier
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[key] = (value, time.time())

        # Disk tier
        disk_path = self._disk_path(key)
        if disk_path:
            try:
                with open(disk_path, "w", encoding="utf-8") as f:
                    json.dump(value, f, ensure_ascii=False)
            except (OSError, TypeError):
                # Disk write failure is non-fatal — memory cache still serves
                logger.debug("fetch.disk_cache_write_failed", key=key)

    def clear(self) -> None:
        """Clear all cached values (memory + disk)."""
        self._cache.clear()
        if self._cache_dir and self._cache_dir.exists():
            for f in self._cache_dir.glob("*.json"):
                # 单个文件删不掉（占用/权限）不该中断整体清理
                with contextlib.suppress(OSError):
                    f.unlink()

    @property
    def memory_size(self) -> int:
        """Number of entries in memory cache."""
        return len(self._cache)


# ═══════════════════════════════════════════════════════════════
# Global instances
# ═══════════════════════════════════════════════════════════════

_cache = HTTPCache(
    max_size=settings.competition_cache_max_size,
    cache_dir=settings.fetcher_cache_dir or None,
)
_circuit_breaker = CircuitBreaker()

# Semaphore is created lazily to respect runtime settings (tests may monkeypatch)
_semaphore: asyncio.Semaphore | None = None
_in_flight = 0


def _get_semaphore() -> asyncio.Semaphore:
    """Get or create the global fetcher semaphore."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(settings.fetcher_semaphore_size)
    return _semaphore


def _reset_semaphore() -> None:
    """Reset semaphore (for tests)."""
    global _semaphore, _in_flight
    _semaphore = None
    _in_flight = 0


# ═══════════════════════════════════════════════════════════════
# Fetch entry point
# ═══════════════════════════════════════════════════════════════


async def fetch(
    url: str,
    *,
    cache_key: str | None = None,
    cache_ttl: int | None = None,
    timeout: int | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    method: str = "GET",
    **kwargs: Any,
) -> dict[str, Any]:
    """Fetch URL with two-tier cache, retry, circuit breaker, and semaphore.

    Args:
        url: URL to fetch
        cache_key: Cache key (default: url)
        cache_ttl: Cache TTL in seconds (default: settings.fetcher_cache_ttl_seconds)
        timeout: Request timeout in seconds (default: 10)
        max_retries: Max retry attempts (default: 3)
        retry_delay: Initial retry delay in seconds (default: 1.0)
        method: HTTP method (default: GET)
        **kwargs: Additional httpx request kwargs

    Returns:
        Response JSON data

    Raises:
        httpx.HTTPError: On network/HTTP errors after retries
        RuntimeError: If circuit breaker is open

    Example:
        data = await fetch(
            "https://api.example.com/data",
            cache_key="example_data",
            cache_ttl=3600
        )
    """
    # Defaults
    cache_key = cache_key or url
    cache_ttl = cache_ttl or settings.fetcher_cache_ttl_seconds
    timeout = timeout or 10

    # Check circuit breaker BEFORE semaphore — OPEN state should fail fast
    # without consuming a semaphore slot (§10.1 验收标准)
    if not _circuit_breaker.allow_request():
        logger.warning("fetch.circuit_open", url=url)
        raise RuntimeError(f"Circuit breaker OPEN for {url}")

    # Check cache (also before semaphore — cache hit needs no slot)
    cached = _cache.get(cache_key, cache_ttl)
    if cached is not None:
        FETCHER_CACHE_HITS.inc()
        logger.debug("fetch.cache_hit", url=url, cache_key=cache_key)
        return cast(dict[str, Any], cached)

    FETCHER_CACHE_MISSES.inc()

    # Acquire semaphore for network request
    global _in_flight
    semaphore = _get_semaphore()
    async with semaphore:
        _in_flight += 1
        FETCHER_SEMAPHORE_USAGE.set(_in_flight)
        try:
            return await _fetch_with_retry(url, cache_key, timeout, max_retries, retry_delay, method, **kwargs)
        finally:
            _in_flight -= 1
            FETCHER_SEMAPHORE_USAGE.set(_in_flight)


async def _fetch_with_retry(
    url: str,
    cache_key: str,
    timeout: int,
    max_retries: int,
    retry_delay: float,
    method: str,
    **kwargs: Any,
) -> dict[str, Any]:
    """Internal: perform HTTP request with retry and cache result on success.

    不收 cache_ttl：写入侧只记时间戳（`_cache.set`），TTL 由读取侧
    `_cache.get(key, ttl)` 判定，因此这里拿到 ttl 也无处可用。
    """
    last_error: Exception | None = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                data = response.json()

            # Success
            _circuit_breaker.record_success()
            _cache.set(cache_key, data)

            logger.info("fetch.success", url=url, attempt=attempt + 1, status=response.status_code)
            return cast(dict[str, Any], data)

        except (httpx.HTTPError, httpx.TimeoutException) as e:
            last_error = e
            _circuit_breaker.record_failure()

            if attempt < max_retries - 1:
                # Exponential backoff: 1s, 2s, 4s, 8s...
                delay = retry_delay * (2**attempt)
                logger.warning(
                    "fetch.retry",
                    url=url,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e),
                    retry_after=delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error("fetch.failed", url=url, attempts=max_retries, error=str(e))

    # All retries exhausted
    # max_retries ≤ 0 时循环不执行、last_error 仍为 None，直接 `raise None`
    # 会抛误导性的 TypeError —— 这里补一个清晰的 RuntimeError。
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"fetch failed for {url} (no attempts made)")


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════


def clear_cache() -> None:
    """Clear HTTP cache (memory + disk, useful for tests)."""
    _cache.clear()
    logger.info("fetch.cache_cleared")


def get_circuit_breaker_state() -> str:
    """Get current circuit breaker state (for monitoring)."""
    return _circuit_breaker.state


def reset_circuit_breaker() -> None:
    """Reset circuit breaker (useful for tests)."""
    _circuit_breaker.state = "CLOSED"
    _circuit_breaker.failures.clear()
    _circuit_breaker._update_metric()
    logger.info("circuit_breaker.reset")


def reset_for_testing() -> None:
    """Reset all global state for test isolation."""
    clear_cache()
    reset_circuit_breaker()


if __name__ == "__main__":
    # Test fetcher
    async def test() -> None:
        # Test cache
        data1 = await fetch("https://httpbin.org/json", cache_ttl=60)
        print("First fetch successful")

        data2 = await fetch("https://httpbin.org/json", cache_ttl=60)
        print("Second fetch (from cache)")

        assert data1 == data2, "Cache should return same data"
        print("Cache working correctly")

        # Test circuit breaker state
        state = get_circuit_breaker_state()
        print(f"Circuit breaker state: {state}")

    asyncio.run(test())
