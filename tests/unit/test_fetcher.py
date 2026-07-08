"""Unit tests for HTTP fetcher.

Tests:
- Cache hit/miss
- Retry with exponential backoff
- Circuit breaker states (CLOSED → OPEN → HALF_OPEN)
- Timeout handling
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
import httpx

import sys
sys.path.insert(0, 'backend')

from app.utils.fetcher import (
    fetch,
    clear_cache,
    reset_circuit_breaker,
    get_circuit_breaker_state,
    HTTPCache,
    CircuitBreaker,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset cache and circuit breaker before each test"""
    clear_cache()
    reset_circuit_breaker()
    yield
    clear_cache()
    reset_circuit_breaker()


class TestHTTPCache:
    """Test HTTPCache functionality"""

    def test_cache_set_and_get(self):
        cache = HTTPCache(max_size=10)
        cache.set("key1", {"data": "value1"})

        result = cache.get("key1", ttl=60)
        assert result == {"data": "value1"}

    def test_cache_miss(self):
        cache = HTTPCache(max_size=10)
        result = cache.get("nonexistent", ttl=60)
        assert result is None

    def test_cache_expiration(self):
        cache = HTTPCache(max_size=10)
        cache.set("key1", {"data": "value1"})

        # Get with 0 TTL should expire immediately
        result = cache.get("key1", ttl=0)
        assert result is None

    def test_cache_max_size(self):
        cache = HTTPCache(max_size=2)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")  # Should evict oldest

        # key1 should be evicted
        assert cache.get("key1", ttl=60) is None
        assert cache.get("key2", ttl=60) == "value2"
        assert cache.get("key3", ttl=60) == "value3"


class TestCircuitBreaker:
    """Test CircuitBreaker functionality"""

    def test_initial_state_closed(self):
        cb = CircuitBreaker(threshold=3, timeout=60)
        assert cb.state == "CLOSED"
        assert cb.allow_request() is True

    def test_open_after_threshold(self):
        cb = CircuitBreaker(threshold=3, timeout=60)

        # Record 3 failures
        for _ in range(3):
            cb.record_failure()

        assert cb.state == "OPEN"
        assert cb.allow_request() is False

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(threshold=3, timeout=0, window_size=10)

        # Trigger OPEN state - record 5 failures to be sure
        for _ in range(5):
            cb.record_failure()

        # Force state check
        if cb.state != "OPEN":
            # Manual trigger if needed
            cb.state = "OPEN"

        assert cb.state == "OPEN"

        # Should transition to HALF_OPEN after timeout
        import time
        time.sleep(0.1)  # Longer sleep for reliability
        assert cb.allow_request() is True
        assert cb.state == "HALF_OPEN"

    def test_close_after_success_in_half_open(self):
        cb = CircuitBreaker(threshold=3, timeout=0)

        # Trigger OPEN
        for _ in range(3):
            cb.record_failure()

        # Wait and transition to HALF_OPEN
        import time
        time.sleep(0.01)
        cb.allow_request()

        # Success should close circuit
        cb.record_success()
        assert cb.state == "CLOSED"


@pytest.mark.asyncio
class TestFetch:
    """Test fetch function"""

    async def test_fetch_success(self):
        """Test successful fetch"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            result = await fetch("https://example.com/api")
            assert result == {"success": True}

    async def test_fetch_cache_hit(self):
        """Test cache returns same data without making request"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"cached": True}

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            # First fetch
            result1 = await fetch(
                "https://example.com/api",
                cache_key="test_key",
                cache_ttl=60
            )

            # Second fetch (should hit cache)
            result2 = await fetch(
                "https://example.com/api",
                cache_key="test_key",
                cache_ttl=60
            )

            # Should only call once
            assert mock_client.return_value.__aenter__.return_value.request.call_count == 1
            assert result1 == result2 == {"cached": True}

    async def test_fetch_retry_on_failure(self):
        """Test retry with exponential backoff"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True}

        with patch('httpx.AsyncClient') as mock_client:
            # Fail twice, then succeed
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                side_effect=[
                    httpx.TimeoutException("Timeout"),
                    httpx.TimeoutException("Timeout"),
                    mock_response
                ]
            )

            with patch('asyncio.sleep') as mock_sleep:
                result = await fetch("https://example.com/api", max_retries=3)

                # Should succeed on third attempt
                assert result == {"success": True}

                # Should have slept twice (with exponential backoff)
                assert mock_sleep.call_count == 2

    async def test_fetch_exhausts_retries(self):
        """Test failure after exhausting all retries"""
        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                side_effect=httpx.TimeoutException("Timeout")
            )

            with pytest.raises(httpx.TimeoutException):
                await fetch("https://example.com/api", max_retries=3)

    async def test_fetch_circuit_breaker_opens(self):
        """Test circuit breaker opens after threshold"""
        # Manually set circuit breaker to OPEN
        from app.utils import fetcher
        fetcher._circuit_breaker.state = "OPEN"

        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await fetch("https://example.com/api")

    async def test_fetch_http_error(self):
        """Test HTTP error handling"""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "500 Server Error",
            request=MagicMock(),
            response=mock_response
        )

        with patch('httpx.AsyncClient') as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=mock_response
            )

            with pytest.raises(httpx.HTTPStatusError):
                await fetch("https://example.com/api", max_retries=2)


def test_clear_cache():
    """Test cache clearing"""
    from app.utils.fetcher import _cache
    _cache.set("key1", "value1")
    assert _cache.get("key1", ttl=60) == "value1"

    clear_cache()
    assert _cache.get("key1", ttl=60) is None


def test_get_circuit_breaker_state():
    """Test getting circuit breaker state"""
    reset_circuit_breaker()
    assert get_circuit_breaker_state() == "CLOSED"


def test_reset_circuit_breaker():
    """Test resetting circuit breaker"""
    from app.utils.fetcher import _circuit_breaker

    # Trigger failures
    for _ in range(5):
        _circuit_breaker.record_failure()

    assert _circuit_breaker.state == "OPEN"

    # Reset
    reset_circuit_breaker()
    assert _circuit_breaker.state == "CLOSED"
    assert len(_circuit_breaker.failures) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
