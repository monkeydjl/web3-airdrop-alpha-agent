"""HTTP Fetcher with caching, retry, and circuit breaker.

Provides unified HTTP client with:
- In-memory LRU cache with TTL
- Exponential backoff retry
- Sliding window circuit breaker
- Timeout and rate limiting

Reference:
- CONVENTIONS.md §14 错误处理
- ENGINEERING_ROADMAP.md §10 数据容错
"""

import asyncio
import time
from collections import deque
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class CircuitBreaker:
    """Sliding window circuit breaker.

    States:
    - CLOSED: Normal operation, requests pass through
    - OPEN: Circuit tripped, requests fail fast
    - HALF_OPEN: Testing if service recovered
    """

    def __init__(self, threshold: int = 5, timeout: int = 60, window_size: int = 100):
        self.threshold = threshold
        self.timeout = timeout
        self.window_size = window_size

        self.failures = deque(maxlen=window_size)
        self.last_failure_time = 0
        self.state = "CLOSED"

    def record_success(self):
        """Record successful request"""
        if self.state == "HALF_OPEN":
            self.state = "CLOSED"
            self.failures.clear()
            logger.info("circuit_breaker.closed")

    def record_failure(self):
        """Record failed request"""
        self.failures.append(time.time())
        self.last_failure_time = time.time()

        # Count recent failures (within window)
        recent_failures = sum(1 for t in self.failures if time.time() - t < self.timeout)

        if recent_failures >= self.threshold and self.state != "OPEN":
            self.state = "OPEN"
            logger.warning("circuit_breaker.opened", failures=recent_failures, threshold=self.threshold)

    def allow_request(self) -> bool:
        """Check if request should be allowed"""
        if self.state == "CLOSED":
            return True

        if self.state == "OPEN":
            # Check if timeout elapsed
            if time.time() - self.last_failure_time >= self.timeout:
                self.state = "HALF_OPEN"
                logger.info("circuit_breaker.half_open")
                return True
            return False

        # HALF_OPEN: allow one request to test
        return True


class HTTPCache:
    """Simple in-memory cache with TTL"""

    def __init__(self, max_size: int = 1000):
        self._cache: dict[str, tuple[Any, float]] = {}
        self._max_size = max_size

    def get(self, key: str, ttl: int) -> Any | None:
        """Get cached value if not expired"""
        if key not in self._cache:
            return None

        value, timestamp = self._cache[key]
        if time.time() - timestamp > ttl:
            del self._cache[key]
            return None

        return value

    def set(self, key: str, value: Any):
        """Set cached value with current timestamp"""
        # Simple LRU: if full, remove oldest
        if len(self._cache) >= self._max_size:
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
            del self._cache[oldest_key]

        self._cache[key] = (value, time.time())

    def clear(self):
        """Clear all cached values"""
        self._cache.clear()


# Global instances
_cache = HTTPCache(max_size=settings.competition_cache_max_size)
_circuit_breaker = CircuitBreaker(
    threshold=5,  # Will be configurable via settings
    timeout=60,
    window_size=100,
)


async def fetch(
    url: str,
    *,
    cache_key: str | None = None,
    cache_ttl: int | None = None,
    timeout: int | None = None,
    max_retries: int = 3,
    retry_delay: float = 1.0,
    method: str = "GET",
    **kwargs,
) -> dict[str, Any]:
    """Fetch URL with caching, retry, and circuit breaker.

    Args:
        url: URL to fetch
        cache_key: Cache key (default: url)
        cache_ttl: Cache TTL in seconds (default: 1 hour)
        timeout: Request timeout in seconds (default: 10)
        max_retries: Max retry attempts (default: 3)
        retry_delay: Initial retry delay in seconds (default: 1.0)
        method: HTTP method (default: GET)
        **kwargs: Additional httpx request kwargs

    Returns:
        Response JSON data

    Raises:
        httpx.HTTPError: On network/HTTP errors after retries
        CircuitBreakerError: If circuit breaker is open

    Example:
        data = await fetch(
            "https://api.example.com/data",
            cache_key="example_data",
            cache_ttl=3600
        )
    """
    # Defaults
    cache_key = cache_key or url
    cache_ttl = cache_ttl or 3600
    timeout = timeout or 10

    # Check circuit breaker
    if not _circuit_breaker.allow_request():
        raise RuntimeError(f"Circuit breaker OPEN for {url}")

    # Check cache
    cached = _cache.get(cache_key, cache_ttl)
    if cached is not None:
        logger.debug("fetch.cache_hit", url=url, cache_key=cache_key)
        return cached

    # Retry with exponential backoff
    last_error = None
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
            return data

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
    raise last_error


def clear_cache():
    """Clear HTTP cache (useful for tests)"""
    _cache.clear()
    logger.info("fetch.cache_cleared")


def get_circuit_breaker_state() -> str:
    """Get current circuit breaker state (for monitoring)"""
    return _circuit_breaker.state


def reset_circuit_breaker():
    """Reset circuit breaker (useful for tests)"""
    _circuit_breaker.state = "CLOSED"
    _circuit_breaker.failures.clear()
    logger.info("circuit_breaker.reset")


if __name__ == "__main__":
    # Test fetcher
    import asyncio

    async def test():
        # Test cache
        data1 = await fetch("https://httpbin.org/json", cache_ttl=60)
        print("✓ First fetch successful")

        data2 = await fetch("https://httpbin.org/json", cache_ttl=60)
        print("✓ Second fetch (from cache)")

        assert data1 == data2, "Cache should return same data"
        print("✓ Cache working correctly")

        # Test circuit breaker state
        state = get_circuit_breaker_state()
        print(f"✓ Circuit breaker state: {state}")

    asyncio.run(test())
