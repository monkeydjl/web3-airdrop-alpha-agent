"""Heat Signal Provider (C3, §6.4 V2).

从 project_signals 表聚合 Twitter 讨论量 + VC 融资信号，
动态调制 sector heat_score。

设计要点：
- 读时缓存：进程内 TTL 缓存（默认 300s），避免每个项目都查 DB
- 降级路径：信号源失败/无数据时，multiplier = 1.0（不影响静态 heat_score）
- 信号维度：按 sector 聚合，不按项目
- 调制范围：multiplier ∈ [min_multiplier, max_multiplier]

Reference:
- ENGINEERING_ROADMAP.md §6.3 V2 增强
- V2_TASKS.md C3
"""

from __future__ import annotations

import threading
import time

import structlog

from app.config import settings
from app.db import get_connection

logger = structlog.get_logger(__name__)


class HeatSignalProvider:
    """按 sector 聚合外部热度信号，输出 heat_score 乘子。

    信号来源（project_signals 表）：
    1. Twitter 讨论量：signal_source='twitter'，按 sector 聚合 signal_strength
    2. VC 融资信号：signal_type='funding'，按 sector 聚合 signal_strength
    3. KOL 信号：signal_source='twitter' + signal_type IN ('airdrop','tge')

    乘子计算：
    - 基准 1.0（无信号时不影响 heat_score）
    - 信号强度越高，乘子越大（上限 max_multiplier）
    - 信号稀少时，乘子降低（下限 min_multiplier）
    """

    def __init__(
        self,
        ttl: float | None = None,
        lookback_hours: int | None = None,
        max_multiplier: float | None = None,
        min_multiplier: float | None = None,
    ) -> None:
        self._ttl = ttl or settings.heat_signal_ttl_seconds
        self._lookback = lookback_hours or settings.heat_signal_lookback_hours
        self._max_mult = max_multiplier or settings.heat_signal_max_multiplier
        self._min_mult = min_multiplier or settings.heat_signal_min_multiplier
        self._cache: dict[str, tuple[float, float]] = {}  # sector → (multiplier, expires_at)
        self._lock = threading.Lock()

    def get_multiplier(self, sector: str) -> float:
        """获取 sector 的热度信号乘子。

        Returns:
            乘子值 ∈ [min_multiplier, max_multiplier]，默认 1.0
        """
        if not settings.heat_signal_enabled:
            return 1.0

        # 缓存命中
        with self._lock:
            entry = self._cache.get(sector)
            if entry is not None:
                multiplier, expires_at = entry
                if time.monotonic() < expires_at:
                    return multiplier
                # 过期，移除
                self._cache.pop(sector, None)

        # 缓存未命中，查询 DB
        try:
            multiplier = self._compute_multiplier(sector)
        except Exception as e:
            logger.warning(
                "heat_signal.compute_failed",
                sector=sector,
                error=str(e),
                fallback="neutral_multiplier",
            )
            multiplier = 1.0

        # 写入缓存
        with self._lock:
            self._cache[sector] = (multiplier, time.monotonic() + self._ttl)

        return multiplier

    def _compute_multiplier(self, sector: str) -> float:
        """从 DB 聚合信号并计算乘子。"""
        conn = get_connection()
        try:
            # 查询近 N 小时内该 sector 相关项目的信号
            # 通过 raw_projects 关联 sector，再 JOIN project_signals
            lookback = self._lookback

            # 1. Twitter 讨论信号：signal_source='twitter' 的信号强度均值
            twitter_row = conn.execute(
                """
                SELECT COUNT(*) as cnt, AVG(ps.signal_strength) as avg_strength
                FROM project_signals ps
                JOIN raw_projects rp ON rp.dedup_key = ps.dedup_key
                    OR rp.project_id = ps.project_id
                WHERE ps.signal_source = 'twitter'
                  AND rp.raw_data LIKE ?
                  AND ps.captured_at >= datetime('now', ?)
                """,
                (f'%"{sector}"%', f"-{lookback} hours"),
            ).fetchone()

            twitter_count = int(twitter_row["cnt"]) if twitter_row and twitter_row["cnt"] else 0
            twitter_strength = (
                float(twitter_row["avg_strength"]) if twitter_row and twitter_row["avg_strength"] else 0.0
            )

            # 2. VC 融资信号：signal_type='funding'
            funding_row = conn.execute(
                """
                SELECT COUNT(*) as cnt, AVG(ps.signal_strength) as avg_strength
                FROM project_signals ps
                JOIN raw_projects rp ON rp.dedup_key = ps.dedup_key
                    OR rp.project_id = ps.project_id
                WHERE ps.signal_type = 'funding'
                  AND rp.raw_data LIKE ?
                  AND ps.captured_at >= datetime('now', ?)
                """,
                (f'%"{sector}"%', f"-{lookback} hours"),
            ).fetchone()

            funding_count = int(funding_row["cnt"]) if funding_row and funding_row["cnt"] else 0
            funding_strength = (
                float(funding_row["avg_strength"]) if funding_row and funding_row["avg_strength"] else 0.0
            )

            # 3. KOL 热度信号：signal_type IN ('airdrop','tge')
            kol_row = conn.execute(
                """
                SELECT COUNT(*) as cnt
                FROM project_signals ps
                JOIN raw_projects rp ON rp.dedup_key = ps.dedup_key
                    OR rp.project_id = ps.project_id
                WHERE ps.signal_type IN ('airdrop', 'tge')
                  AND ps.signal_source = 'twitter'
                  AND rp.raw_data LIKE ?
                  AND ps.captured_at >= datetime('now', ?)
                """,
                (f'%"{sector}"%', f"-{lookback} hours"),
            ).fetchone()

            kol_count = int(kol_row["cnt"]) if kol_row and kol_row["cnt"] else 0
        finally:
            conn.close()

        # 无信号时返回中性乘子
        total_signals = twitter_count + funding_count + kol_count
        if total_signals == 0:
            return 1.0

        # 信号强度加权：Twitter 讨论量 40% + VC 融资 40% + KOL 热度 20%
        twitter_component = min(1.0, twitter_count / 20.0) * twitter_strength  # 20 条讨论 = 满分
        funding_component = min(1.0, funding_count / 5.0) * funding_strength  # 5 条融资 = 满分
        kol_component = min(1.0, kol_count / 10.0)  # 10 条 KOL 信号 = 满分

        signal_score = twitter_component * 0.4 + funding_component * 0.4 + kol_component * 0.2

        # 映射到乘子：signal_score=0 → 1.0（中性），signal_score=1.0 → max_multiplier
        # 信号极度稀少时乘子降低（低于 0.1 阈值）
        if signal_score < 0.1 and total_signals > 0:
            # 有少量信号但强度极低 → 轻微降温
            multiplier = 1.0 - (0.1 - signal_score) * 3.0
        else:
            # 正常映射
            multiplier = 1.0 + (signal_score * (self._max_mult - 1.0))

        # 钳制到 [min_multiplier, max_multiplier]
        multiplier = max(self._min_mult, min(self._max_mult, multiplier))

        logger.debug(
            "heat_signal.computed",
            sector=sector,
            twitter_count=twitter_count,
            funding_count=funding_count,
            kol_count=kol_count,
            signal_score=round(signal_score, 3),
            multiplier=round(multiplier, 3),
        )

        return multiplier

    def invalidate(self, sector: str | None = None) -> None:
        """失效缓存项。"""
        with self._lock:
            if sector:
                self._cache.pop(sector, None)
            else:
                self._cache.clear()


# ── 模块级单例 ──────────────────────────────────────────────────
_provider: HeatSignalProvider | None = None
_singleton_lock = threading.Lock()


def get_heat_signal_provider() -> HeatSignalProvider:
    """获取全局 HeatSignalProvider 单例。"""
    global _provider
    if _provider is None:
        with _singleton_lock:
            if _provider is None:
                _provider = HeatSignalProvider()
    return _provider


def reset_heat_signal_provider() -> None:
    """重置全局单例（仅用于测试）。"""
    global _provider
    with _singleton_lock:
        _provider = None
