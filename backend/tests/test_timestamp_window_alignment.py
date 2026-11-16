"""时间戳窗口比较的格式对齐回归（2026-11-13 审查 P2-7）。

背景：`captured_at` / `started_at` 由应用层用 `datetime.isoformat()` 写入
（`2026-11-13T08:00:00+00:00`，T 分隔），而查询里的 cutoff 用 SQL
`datetime('now', '-N hours')` 生成（`2026-11-13 08:00:00`，空格分隔）。
SQLite 的 TIMESTAMP 实为 TEXT，`>=` 是字符串比较：`T`(0x54) > 空格(0x20)，
**同日期的行无论几点都判成大于 cutoff** —— 边界日的窗口最多多算一天
（archive.py::_cutoff_db_default 的 docstring 实测记录过同一个坑）。

修复：应用层用与写入相同的 T 格式计算 cutoff，绑定参数替代
`datetime('now', ?)`。测试用固定时钟，全天候确定性。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.db import init_db

_NOW = datetime(2026, 11, 13, 14, 0, tzinfo=UTC)


class _FixedDatetime(datetime):
    """datetime 替身：now() 恒为 _NOW，让窗口断言与真实时间无关。"""

    @classmethod
    def now(cls, tz: object | None = None) -> datetime:  # noqa: ARG003 - 签名对齐真实 datetime
        return _NOW


@pytest.fixture
def conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def _seed_raw(conn: sqlite3.Connection, dedup_key: str, sector: str) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at)
        VALUES (?, 'twitter_keyword', ?, ?, ?)
        """,
        (f"raw-{dedup_key}", dedup_key, f'{{"name": "P", "sector": "{sector}"}}', _NOW.isoformat()),
    )


def _seed_signal(
    conn: sqlite3.Connection, dedup_key: str, signal_id: str, captured_at: datetime, strength: float
) -> None:
    conn.execute(
        """
        INSERT INTO project_signals (signal_id, dedup_key, signal_type, signal_source,
                                     signal_data, signal_strength, captured_at)
        VALUES (?, ?, 'twitter_mention', 'twitter', '{}', ?, ?)
        """,
        (signal_id, dedup_key, strength, captured_at.isoformat()),
    )


class TestHeatSignalsWindow:
    @staticmethod
    def _patch_scope(monkeypatch: pytest.MonkeyPatch, conn: sqlite3.Connection) -> None:
        """HeatSignalProvider 经 connection_scope 自开连接 —— 注入本用例的内存库。"""
        import contextlib

        import app.agents.heat_signals as hs

        @contextlib.contextmanager
        def _scope(*args: object, **kwargs: object) -> object:
            yield conn

        monkeypatch.setattr(hs, "connection_scope", _scope)

    def test_same_day_row_outside_window_is_excluded(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NOW-7h 的行（同日、早于 6h cutoff）不得进入窗口。

        buggy 口径：cutoff 是空格格式 '2026-11-13 08:00:00'，行是 T 格式
        '2026-11-13T07:00:00' —— 同日期前缀相等后 T>空格，整行被判"在窗口内"。
        """
        import app.agents.heat_signals as hs

        # raising=False：修复前该模块还没有 datetime import（'now' 交给 SQL），
        # 修复后才需要固定时钟。
        monkeypatch.setattr(hs, "datetime", _FixedDatetime, raising=False)
        monkeypatch.setattr(hs.settings, "heat_signal_enabled", True)
        self._patch_scope(monkeypatch, conn)
        _seed_raw(conn, "alpha-defi", "DeFi")
        # 只有 NOW-7h 一条（6h 窗口外），强度拉满：若被误算入，乘子必偏离中性 1.0
        _seed_signal(conn, "alpha-defi", "sig-old", _NOW - timedelta(hours=7), strength=1.0)
        conn.commit()

        provider = hs.HeatSignalProvider(ttl=0.0, lookback_hours=6)
        multiplier = provider.get_multiplier("DeFi")

        assert multiplier == 1.0, (
            f"窗口外（NOW-7h > 6h lookback）的信号被计入：multiplier={multiplier} —— cutoff 与列的写入格式（T）没有对齐"
        )

    def test_in_window_row_still_counts(self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
        """修完不能矫枉过正：窗口内的行要照常生效。"""
        import app.agents.heat_signals as hs

        monkeypatch.setattr(hs, "datetime", _FixedDatetime, raising=False)
        monkeypatch.setattr(hs.settings, "heat_signal_enabled", True)
        self._patch_scope(monkeypatch, conn)
        _seed_raw(conn, "alpha-defi", "DeFi")
        _seed_signal(conn, "alpha-defi", "sig-new", _NOW - timedelta(hours=1), strength=1.0)
        conn.commit()

        provider = hs.HeatSignalProvider(ttl=0.0, lookback_hours=6)
        assert provider.get_multiplier("DeFi") != 1.0


class TestLatencyMetricsWindow:
    def test_same_day_row_outside_window_is_excluded(
        self, conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """collection_logs.started_at 同日早于 6h cutoff 的行不得计入延迟样本。"""
        import app.collectors.metrics as metrics_mod

        monkeypatch.setattr(metrics_mod, "datetime", _FixedDatetime)
        old = (_NOW - timedelta(hours=7)).isoformat()
        recent = (_NOW - timedelta(hours=1)).isoformat()
        for log_id, started in (("log-old", old), ("log-new", recent)):
            conn.execute(
                "INSERT INTO collection_logs (log_id, source_id, started_at, finished_at, status)"
                " VALUES (?, 'defillama', ?, ?, 'success')",
                (log_id, started, started),
            )
        conn.commit()

        snapshot = metrics_mod.CollectionMetrics(conn).get_latency_metrics(window_hours=6)

        assert snapshot.total_runs == 1, (
            f"窗口外的采集记录被计入（total_runs={snapshot.total_runs}）—— cutoff 与列的写入格式（T）没有对齐"
        )
