"""Competition Sector Count Cache (ADR-010 V2).

进程内 LRU 缓存，用于 competition 子分计算。
TTL 300s（5min），写时失效（invalidate-on-write），读时重建（read-through）。

Reference:
- ADR-010-competition-cache.md §V2（单进程）：进程内 LRU 缓存
- ENGINEERING_ROADMAP.md §7.5
"""

from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

import structlog

from app.metrics import (
    COMPETITION_CACHE_DB_DURATION,
    COMPETITION_CACHE_HITS,
    COMPETITION_CACHE_MISSES,
)

logger = structlog.get_logger(__name__)

# 默认 TTL 300 秒（5 min），与 ADR-010 规格一致
_DEFAULT_TTL = 300.0
# 默认 LRU 容量 256（sector 种类有限，绰绰有余）
_DEFAULT_MAX_SIZE = 256


class SectorCountCache:
    """LRU + TTL 缓存，存储 sector → project count。

    线程安全：所有读写操作通过内部 threading.Lock 保护。

    用法:
        cache = SectorCountCache()
        count = cache.get_or_compute("DeFi", lambda: repo.count_by_sector("DeFi"))
        cache.invalidate("DeFi")  # 写入项目后失效
    """

    def __init__(
        self,
        ttl: float = _DEFAULT_TTL,
        max_size: int = _DEFAULT_MAX_SIZE,
    ) -> None:
        self._ttl = ttl
        self._max_size = max_size
        self._store: OrderedDict[str, tuple[int, float]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, sector: str) -> int | None:
        """尝试从缓存读取，命中返回 count，未命中或过期返回 None。"""
        with self._lock:
            entry = self._store.get(sector)
            if entry is None:
                COMPETITION_CACHE_MISSES.inc()
                return None

            count, expires_at = entry
            if time.monotonic() >= expires_at:
                # 过期，移除
                self._store.pop(sector, None)
                COMPETITION_CACHE_MISSES.inc()
                return None

            # 命中，移到末尾（LRU 最近使用）
            self._store.move_to_end(sector)
            COMPETITION_CACHE_HITS.inc()
            return count

    def get_or_compute(
        self,
        sector: str,
        compute_fn: Callable[[], int],
    ) -> int:
        """读时重建（read-through）：缓存命中直接返回，未命中调 compute_fn 并写入缓存。

        Args:
            sector: 赛道名
            compute_fn: 缓存未命中时的计算函数（通常是 DB COUNT(*)）

        Returns:
            该 sector 的项目数
        """
        cached = self.get(sector)
        if cached is not None:
            return cached

        # 缓存未命中，执行计算
        start = time.monotonic()
        count = compute_fn()
        db_duration = time.monotonic() - start

        COMPETITION_CACHE_DB_DURATION.observe(db_duration)

        self.put(sector, count)
        return count

    def put(self, sector: str, count: int) -> None:
        """写入缓存项。"""
        with self._lock:
            # 如果已存在，先移除再插入（更新位置）
            if sector in self._store:
                self._store.pop(sector)

            # LRU 淘汰
            while len(self._store) >= self._max_size:
                self._store.popitem(last=False)

            self._store[sector] = (count, time.monotonic() + self._ttl)

    def invalidate(self, sector: str) -> None:
        """写时失效：写入项目后使对应 sector 缓存项失效。"""
        with self._lock:
            removed = self._store.pop(sector, None)
            if removed is not None:
                logger.debug("competition_cache.invalidated", sector=sector)

    def invalidate_all(self) -> None:
        """清空全部缓存（用于全量重建场景）。"""
        with self._lock:
            n = len(self._store)
            self._store.clear()
            if n > 0:
                logger.debug("competition_cache.invalidated_all", entries=n)

    def stats(self) -> dict[str, int]:
        """返回缓存统计信息（用于调试/监控）。"""
        with self._lock:
            return {
                "entries": len(self._store),
                "max_size": self._max_size,
                "ttl_seconds": int(self._ttl),
            }

    def snapshot(self) -> dict[str, int]:
        """返回当前缓存内容的快照（用于一致性比对）。"""
        with self._lock:
            now = time.monotonic()
            return {sector: count for sector, (count, expires_at) in self._store.items() if now < expires_at}


# ── 模块级单例 ──────────────────────────────────────────────────
# 全局单例，供 orchestrator / repository 共享
_sector_count_cache: SectorCountCache | None = None
_singleton_lock = threading.Lock()


def get_sector_count_cache() -> SectorCountCache:
    """获取全局 SectorCountCache 单例。"""
    global _sector_count_cache
    if _sector_count_cache is None:
        with _singleton_lock:
            if _sector_count_cache is None:
                _sector_count_cache = SectorCountCache()
    return _sector_count_cache


def reset_sector_count_cache() -> None:
    """重置全局单例（仅用于测试）。"""
    global _sector_count_cache
    with _singleton_lock:
        _sector_count_cache = None
