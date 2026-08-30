"""Tests for fetcher V2 enhancements (B1, §10.1).

Covers:
- Two-tier cache: in-memory + disk persistence
- Semaphore concurrency gate (fetcher_semaphore_size)
- Configurable circuit breaker (settings-driven)
- Prometheus metrics: cache hit/miss, semaphore usage, CB state
- Circuit breaker OPEN → fail fast without consuming semaphore

Reference:
- V2_TASKS.md B1
- ENGINEERING_ROADMAP.md §10.1
"""

from __future__ import annotations

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.utils import fetcher
from app.utils.fetcher import (
    CircuitBreaker,
    HTTPCache,
    clear_cache,
    fetch,
    reset_circuit_breaker,
)


@pytest.fixture(autouse=True)
def _reset_state(monkeypatch):
    """Reset cache, circuit breaker, and semaphore before each test.

    本文件用 `https://example.com` 作占位 URL 测缓存/熔断/信号量的内部行为，
    不关心域名白名单（那层由 `test_domain_allowlist.py` 单独覆盖）——把
    `assert_url_allowed` 变 no-op，让测试专注 fetcher 自身逻辑。
    """
    monkeypatch.setattr(fetcher, "assert_url_allowed", lambda url: None)
    clear_cache()
    reset_circuit_breaker()
    fetcher._reset_semaphore()
    yield
    clear_cache()
    reset_circuit_breaker()
    fetcher._reset_semaphore()


def _mock_response(status=200, json_data=None):
    """Create a mock httpx response."""
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = json_data or {"ok": True}
    resp.raise_for_status = MagicMock()
    if status >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(f"{status} Error", request=MagicMock(), response=resp)
    return resp


# ═══════════════════════════════════════════════════════════════
# Two-tier Cache (in-memory + disk)
# ═══════════════════════════════════════════════════════════════


class TestTwoTierCache:
    """Test HTTPCache with disk persistence."""

    def test_disk_cache_write_and_read(self, tmp_path):
        """Disk cache persists and reads back JSON data."""
        cache = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        cache.set("disk_key", {"data": "persisted"})

        # New cache instance reads from disk (simulates restart)
        cache2 = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        result = cache2.get("disk_key", ttl=3600)
        assert result == {"data": "persisted"}

    def test_disk_cache_skipped_when_no_dir(self):
        """No cache_dir means disk tier is disabled."""
        cache = HTTPCache(max_size=10, cache_dir=None)
        cache.set("key1", {"v": 1})

        # Memory should still work
        assert cache.get("key1", ttl=60) == {"v": 1}

        # Disk path should be None
        assert cache._disk_path("key1") is None

    def test_disk_cache_expiration(self, tmp_path):
        """Disk cache entries expire after TTL."""
        cache = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        cache.set("expire_key", {"v": 1})

        # Get with TTL=0 should expire
        result = cache.get("expire_key", ttl=0)
        assert result is None

    def test_ttl_zero_never_serves_cache(self, tmp_path):
        """ttl=0 语义是"不缓存"，必须每次都 miss。

        回归：原实现用 `time.time() - ts > ttl`，在 Windows（时钟分辨率约 15.6ms）
        上同一时刻 set 后立即 get(ttl=0) 得到 `0 > 0 == False`，于是返回本该过期
        的数据——实测 20 次里 14 次命中脏数据。边界必须是 >=。
        重复多轮，确保不是碰巧躲过时钟跳变。
        """
        for i in range(25):
            cache = HTTPCache(max_size=10, cache_dir=str(tmp_path / f"round{i}"))
            cache.set("k", {"v": i})
            assert cache.get("k", ttl=0) is None, f"ttl=0 served stale cache on round {i}"

    def test_ttl_zero_memory_tier_only(self):
        """内存层单独也必须遵守 ttl=0（磁盘层关闭时不能漏判）。"""
        for i in range(25):
            cache = HTTPCache(max_size=10, cache_dir=None)
            cache.set("k", {"v": i})
            assert cache.get("k", ttl=0) is None, f"memory tier served stale cache on round {i}"

    def test_disk_cache_clear_removes_files(self, tmp_path):
        """clear() removes disk cache files."""
        cache = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        cache.set("key1", {"v": 1})
        cache.set("key2", {"v": 2})

        # Verify files exist
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 2

        cache.clear()

        # Verify files removed
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 0

    def test_disk_cache_corrupt_file_handled(self, tmp_path):
        """Corrupt disk cache file is removed gracefully."""
        cache = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        cache.set("corrupt_key", {"v": 1})

        # Corrupt the disk file
        disk_path = cache._disk_path("corrupt_key")
        disk_path.write_text("NOT JSON")

        # Clear memory so disk is the only source
        cache._cache.clear()

        # Should return None (corrupt file removed)
        result = cache.get("corrupt_key", ttl=3600)
        assert result is None
        assert not disk_path.exists()

    def test_memory_eviction_does_not_affect_disk(self, tmp_path):
        """When memory evicts an entry, disk copy persists."""
        cache = HTTPCache(max_size=2, cache_dir=str(tmp_path))
        cache.set("key1", {"v": 1})
        cache.set("key2", {"v": 2})
        cache.set("key3", {"v": 3})  # Evicts key1 from memory

        # key1 not in memory, but should be on disk
        assert cache.get("key1", ttl=3600) == {"v": 1}

    def test_disk_cache_key_hashing(self, tmp_path):
        """Disk cache uses SHA-256 hash of key as filename."""
        cache = HTTPCache(max_size=10, cache_dir=str(tmp_path))
        long_url = "https://api.example.com/v3/very/long/path?param=value&other=stuff"
        cache.set(long_url, {"data": True})

        # File should be a hash, not the raw URL
        files = list(tmp_path.glob("*.json"))
        assert len(files) == 1
        # SHA-256 hex is 64 chars + .json
        assert len(files[0].stem) == 64


# ═══════════════════════════════════════════════════════════════
# Semaphore Concurrency Control
# ═══════════════════════════════════════════════════════════════


class TestSemaphoreControl:
    """Test fetcher semaphore integration."""

    async def test_semaphore_limits_concurrency(self, monkeypatch):
        """Semaphore enforces max_concurrent limit."""
        monkeypatch.setattr("app.config.settings.fetcher_semaphore_size", 2)
        fetcher._reset_semaphore()

        call_count = 0
        max_concurrent = 0
        current = 0

        async def mock_request(*args, **kwargs):
            nonlocal call_count, max_concurrent, current
            call_count += 1
            current += 1
            max_concurrent = max(max_concurrent, current)
            await asyncio.sleep(0.05)
            current -= 1
            return _mock_response(json_data={"ok": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=mock_request)
            # Launch 5 concurrent requests with semaphore=2
            await asyncio.gather(*[fetch(f"https://example.com/{i}") for i in range(5)])

        assert call_count == 5
        assert max_concurrent <= 2

    async def test_cache_hit_does_not_consume_semaphore(self, monkeypatch):
        """Cache hits bypass the semaphore entirely."""
        monkeypatch.setattr("app.config.settings.fetcher_semaphore_size", 1)
        fetcher._reset_semaphore()

        # Pre-populate cache
        fetcher._cache.set("cached_url", {"from_cache": True})

        request_calls = 0

        async def mock_request(*args, **kwargs):
            nonlocal request_calls
            request_calls += 1
            return _mock_response(json_data={"from_network": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=mock_request)
            # Cache hit — should not call network at all
            result = await fetch("https://example.com/api", cache_key="cached_url", cache_ttl=60)

        assert result == {"from_cache": True}
        assert request_calls == 0

    async def test_circuit_open_does_not_consume_semaphore(self, monkeypatch):
        """Circuit breaker OPEN state fails fast without semaphore."""
        monkeypatch.setattr("app.config.settings.fetcher_semaphore_size", 1)
        fetcher._reset_semaphore()

        # Force circuit breaker open with a recent failure time
        fetcher._circuit_breaker.state = "OPEN"
        fetcher._circuit_breaker.last_failure_time = time.time()

        request_calls = 0

        async def mock_request(*args, **kwargs):
            nonlocal request_calls
            request_calls += 1
            return _mock_response()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=mock_request)
            with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
                await fetch("https://example.com/api")

        # No network request should have been made
        assert request_calls == 0
        # Semaphore should not have been acquired
        assert fetcher._in_flight == 0


# ═══════════════════════════════════════════════════════════════
# Configurable Circuit Breaker
# ═══════════════════════════════════════════════════════════════


class TestConfigurableCircuitBreaker:
    """Test circuit breaker with settings-driven configuration."""

    def test_uses_settings_defaults(self, monkeypatch):
        """CB reads threshold/timeout from settings when not explicitly passed."""
        monkeypatch.setattr("app.config.settings.fetcher_circuit_breaker_threshold", 3)
        monkeypatch.setattr("app.config.settings.fetcher_circuit_breaker_timeout_seconds", 30)

        cb = CircuitBreaker()
        assert cb.threshold == 3
        assert cb.timeout == 30

    def test_explicit_params_override_settings(self, monkeypatch):
        """Explicit constructor params take priority over settings."""
        monkeypatch.setattr("app.config.settings.fetcher_circuit_breaker_threshold", 10)

        cb = CircuitBreaker(threshold=2)
        assert cb.threshold == 2

    def test_open_at_configured_threshold(self, monkeypatch):
        """CB opens exactly at settings.fetcher_circuit_breaker_threshold."""
        monkeypatch.setattr("app.config.settings.fetcher_circuit_breaker_threshold", 3)
        monkeypatch.setattr("app.config.settings.fetcher_circuit_breaker_timeout_seconds", 60)

        cb = CircuitBreaker()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == "CLOSED"  # 2 < 3

        cb.record_failure()
        assert cb.state == "OPEN"  # 3 >= 3

    async def test_open_state_fails_fast(self):
        """OPEN circuit breaker raises RuntimeError on fetch."""
        fetcher._circuit_breaker.state = "OPEN"
        fetcher._circuit_breaker.last_failure_time = time.time()

        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await fetch("https://example.com/blocked")


# ═══════════════════════════════════════════════════════════════
# Prometheus Metrics
# ═══════════════════════════════════════════════════════════════


class TestFetcherMetrics:
    """Test Prometheus metric exposure."""

    async def test_cache_hit_increments_counter(self, monkeypatch):
        """Cache hit increments FETCHER_CACHE_HITS."""
        from app.metrics import FETCHER_CACHE_HITS, metric_sample_value

        # Record initial value
        before = metric_sample_value(FETCHER_CACHE_HITS)

        # Pre-populate cache
        fetcher._cache.set("metric_hit", {"v": 1})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=_mock_response(json_data={"v": 1})
            )
            await fetch("https://example.com/metric", cache_key="metric_hit", cache_ttl=60)

        after = metric_sample_value(FETCHER_CACHE_HITS)
        assert after > before

    async def test_cache_miss_increments_counter(self, monkeypatch):
        """Cache miss increments FETCHER_CACHE_MISSES."""
        from app.metrics import FETCHER_CACHE_MISSES, metric_sample_value

        before = metric_sample_value(FETCHER_CACHE_MISSES)

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=_mock_response(json_data={"v": 1})
            )
            await fetch("https://example.com/miss", cache_key="metric_miss", cache_ttl=60)

        after = metric_sample_value(FETCHER_CACHE_MISSES)
        assert after > before

    async def test_semaphore_usage_gauge_tracks_in_flight(self, monkeypatch):
        """FETCHER_SEMAPHORE_USAGE reflects in-flight requests."""
        from app.metrics import FETCHER_SEMAPHORE_USAGE, metric_sample_value

        monkeypatch.setattr("app.config.settings.fetcher_semaphore_size", 1)
        fetcher._reset_semaphore()

        started = asyncio.Event()
        proceed = asyncio.Event()

        async def slow_request(*args, **kwargs):
            started.set()
            await proceed.wait()
            return _mock_response(json_data={"slow": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=slow_request)
            task = asyncio.create_task(fetch("https://example.com/slow"))

            await started.wait()
            # While request is in flight, gauge should be 1
            assert metric_sample_value(FETCHER_SEMAPHORE_USAGE) == 1.0

            proceed.set()
            await task

        # After completion, gauge should be 0
        assert metric_sample_value(FETCHER_SEMAPHORE_USAGE) == 0.0

    def test_circuit_breaker_state_metric(self):
        """FETCHER_CIRCUIT_BREAKER_STATE reflects CB state."""
        from app.metrics import FETCHER_CIRCUIT_BREAKER_STATE, metric_sample_value

        cb = fetcher._circuit_breaker

        cb.state = "CLOSED"
        cb._update_metric()
        assert metric_sample_value(FETCHER_CIRCUIT_BREAKER_STATE) == 0.0

        cb.state = "OPEN"
        cb._update_metric()
        assert metric_sample_value(FETCHER_CIRCUIT_BREAKER_STATE) == 2.0

        cb.state = "HALF_OPEN"
        cb._update_metric()
        assert metric_sample_value(FETCHER_CIRCUIT_BREAKER_STATE) == 1.0


# ═══════════════════════════════════════════════════════════════
# Integration: fetch with disk cache
# ═══════════════════════════════════════════════════════════════


class TestFetchDiskCacheIntegration:
    """End-to-end: fetch writes to disk cache, second fetch hits disk."""

    async def test_fetch_persists_to_disk(self, tmp_path, monkeypatch):
        """Successful fetch writes response to disk cache."""
        monkeypatch.setattr("app.config.settings.fetcher_cache_dir", str(tmp_path))
        # Recreate cache with new dir
        fetcher._cache = HTTPCache(
            max_size=100,
            cache_dir=str(tmp_path),
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(
                return_value=_mock_response(json_data={"persisted": True})
            )
            result = await fetch(
                "https://example.com/disk-test",
                cache_key="disk_test",
                cache_ttl=3600,
            )

        assert result == {"persisted": True}

        # Verify disk file was created
        json_files = list(tmp_path.glob("*.json"))
        assert len(json_files) == 1
        disk_data = json.loads(json_files[0].read_text())
        assert disk_data == {"persisted": True}

    async def test_second_fetch_hits_disk_cache(self, tmp_path, monkeypatch):
        """Second fetch reads from disk (no network call)."""
        monkeypatch.setattr("app.config.settings.fetcher_cache_dir", str(tmp_path))

        # Use a standalone cache to avoid global state interference
        test_cache = HTTPCache(max_size=100, cache_dir=str(tmp_path))
        fetcher._cache = test_cache

        network_calls = 0

        async def mock_request(*args, **kwargs):
            nonlocal network_calls
            network_calls += 1
            return _mock_response(json_data={"from_network": True})

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.request = AsyncMock(side_effect=mock_request)
            # First fetch — network call
            r1 = await fetch("https://example.com/c1", cache_key="c1", cache_ttl=3600)
            assert r1 == {"from_network": True}
            assert network_calls == 1

            # Clear memory cache so only disk can serve
            test_cache._cache.clear()

            # Second fetch — should hit disk
            r2 = await fetch("https://example.com/c1", cache_key="c1", cache_ttl=3600)
            assert r2 == {"from_network": True}
            assert network_calls == 1  # No additional network call
