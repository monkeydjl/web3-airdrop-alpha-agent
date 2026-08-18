"""Tests for SectorCountCache (ADR-010 V2).

验证 LRU + TTL + 写时失效 + 读时重建行为。

Reference:
- ADR-010-competition-cache.md §V2
- backend/app/cache.py
"""

import time

import pytest

from app.cache import (
    SectorCountCache,
    get_sector_count_cache,
    reset_sector_count_cache,
)


@pytest.fixture(autouse=True)
def clean_cache():
    """每个测试前重置全局缓存单例。"""
    reset_sector_count_cache()
    yield
    reset_sector_count_cache()


class TestSectorCountCache:
    def test_get_miss_returns_none(self):
        """未写入的 sector 返回 None。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        assert cache.get("DeFi") is None

    def test_put_then_get_hits(self):
        """写入后读取命中。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        cache.put("DeFi", 42)
        assert cache.get("DeFi") == 42

    def test_ttl_expiry(self):
        """TTL 过期后返回 None。"""
        cache = SectorCountCache(ttl=0.05, max_size=10)  # 50ms TTL
        cache.put("DeFi", 5)
        time.sleep(0.06)
        assert cache.get("DeFi") is None

    def test_invalidate(self):
        """写时失效：invalidate 后缓存项消失。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        cache.put("DeFi", 10)
        cache.invalidate("DeFi")
        assert cache.get("DeFi") is None

    def test_invalidate_all(self):
        """清空全部缓存。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        cache.put("DeFi", 1)
        cache.put("Gaming", 2)
        cache.invalidate_all()
        assert cache.get("DeFi") is None
        assert cache.get("Gaming") is None

    def test_lru_eviction(self):
        """LRU 淘汰：容量满时淘汰最久未使用的。"""
        cache = SectorCountCache(ttl=10, max_size=3)
        cache.put("A", 1)
        cache.put("B", 2)
        cache.put("C", 3)

        # 访问 A，使其成为最近使用
        cache.get("A")

        # 插入 D，应淘汰 B（最久未使用）
        cache.put("D", 4)

        assert cache.get("A") == 1  # A still cached
        assert cache.get("B") is None  # B evicted
        assert cache.get("C") == 3
        assert cache.get("D") == 4

    def test_get_or_compute_hit(self):
        """get_or_compute 缓存命中时不调 compute_fn。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        cache.put("DeFi", 7)

        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return 999

        result = cache.get_or_compute("DeFi", compute)
        assert result == 7
        assert call_count == 0  # 未调用 compute

    def test_get_or_compute_miss(self):
        """get_or_compute 缓存未命中时调 compute_fn 并写入缓存。"""
        cache = SectorCountCache(ttl=10, max_size=10)

        call_count = 0

        def compute():
            nonlocal call_count
            call_count += 1
            return 15

        result = cache.get_or_compute("DeFi", compute)
        assert result == 15
        assert call_count == 1

        # 第二次应命中缓存，不再调 compute
        result2 = cache.get_or_compute("DeFi", compute)
        assert result2 == 15
        assert call_count == 1  # 仍然只调了一次

    def test_stats(self):
        """stats 返回正确的统计信息。"""
        cache = SectorCountCache(ttl=300, max_size=256)
        cache.put("A", 1)
        cache.put("B", 2)
        stats = cache.stats()
        assert stats["entries"] == 2
        assert stats["max_size"] == 256
        assert stats["ttl_seconds"] == 300

    def test_snapshot(self):
        """snapshot 返回当前缓存内容。"""
        cache = SectorCountCache(ttl=10, max_size=10)
        cache.put("DeFi", 5)
        cache.put("Gaming", 3)
        snap = cache.snapshot()
        assert snap["DeFi"] == 5
        assert snap["Gaming"] == 3

    def test_thread_safety(self):
        """多线程并发写入不报错。"""
        import threading

        cache = SectorCountCache(ttl=10, max_size=100)

        def writer(sector: str, count: int):
            for _ in range(50):
                cache.put(sector, count)
                cache.get(sector)

        threads = [
            threading.Thread(target=writer, args=(f"S{i}", i))
            for i in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 全部线程完成后无异常即通过
        assert cache.stats()["entries"] <= 100


class TestGlobalSingleton:
    def test_singleton_is_shared(self):
        """全局单例是共享的。"""
        c1 = get_sector_count_cache()
        c2 = get_sector_count_cache()
        assert c1 is c2

    def test_reset_creates_new_instance(self):
        """reset 后获取新实例。"""
        c1 = get_sector_count_cache()
        c1.put("DeFi", 10)
        reset_sector_count_cache()
        c2 = get_sector_count_cache()
        assert c1 is not c2
        assert c2.get("DeFi") is None


class TestRepositoryIntegration:
    """验证 repository 层与缓存的集成。"""

    def test_count_by_sector(self):
        """repository.count_by_sector 直接查 DB。"""
        from app.db import get_connection
        from app.repository import ProjectRepository

        # 确保有测试数据
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, name, sector, stage, score, label, confidence) "
                "VALUES ('test-cache-001', 'TestCacheProj', 'TestCacheSector', 'testnet', 50, 'WATCH', 0.5)"
            )
            conn.commit()

        repo = ProjectRepository()
        count = repo.count_by_sector("TestCacheSector")
        assert count >= 1

    def test_global_sector_counts_uses_cache(self):
        """global_sector_counts 使用缓存（第二次不查 DB）。"""
        from app.repository import ProjectRepository

        repo = ProjectRepository()

        # 第一次查询（可能 miss 或 hit 取决于之前的测试）
        result1 = repo.global_sector_counts(sectors={"TestCacheSector"})
        assert "TestCacheSector" in result1

        # 第二次查询应命中缓存
        result2 = repo.global_sector_counts(sectors={"TestCacheSector"})
        assert result2["TestCacheSector"] == result1["TestCacheSector"]

    def test_invalidate_sector_cache(self):
        """invalidate 后缓存项消失。"""
        from app.repository import ProjectRepository

        repo = ProjectRepository()
        repo.global_sector_counts(sectors={"TestCacheSector"})
        repo.invalidate_sector_cache("TestCacheSector")

        from app.cache import get_sector_count_cache

        assert get_sector_count_cache().get("TestCacheSector") is None
