"""Tests for collection quality metrics.

Reference:
- backend/app/collectors/metrics.py
- DATA_QUALITY.md
- OBSERVABILITY.md
"""

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.collectors.metrics import CollectionMetrics
from app.db import init_db


@pytest.fixture
def metrics():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield CollectionMetrics(conn)
    conn.close()


def _insert_collection_log(
    conn,
    source_id,
    status,
    started_at,
    finished_at=None,
    items_collected=0,
    items_duplicate=0,
):
    import uuid

    conn.execute(
        """
        INSERT INTO collection_logs (
            log_id, source_id, started_at, finished_at,
            items_collected, items_duplicate, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid.uuid4().hex,
            source_id,
            started_at,
            finished_at,
            items_collected,
            items_duplicate,
            status,
        ),
    )
    conn.commit()


def _insert_source(conn, source_id, sync_status="success", last_sync=None):
    conn.execute(
        """
        INSERT INTO data_sources (source_id, source_type, source_name, sync_status, last_sync)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(source_id) DO UPDATE SET
            sync_status = excluded.sync_status,
            last_sync = excluded.last_sync,
            updated_at = datetime('now')
        """,
        (source_id, "api", source_id, sync_status, last_sync),
    )
    conn.commit()


def _insert_raw_project(conn, source_id, raw_data, discovered_at=None):
    discovered_at = discovered_at or datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (f"raw-{source_id}", source_id, "dedup", raw_data, discovered_at, 0.5),
    )
    conn.commit()


class TestLatencyMetrics:
    def test_success_rate_calculation(self, metrics):
        now = datetime.now(UTC)
        _insert_collection_log(metrics._get_conn(), "defillama", "success", now, now, 10, 0)
        _insert_collection_log(metrics._get_conn(), "defillama", "error", now, now, 0, 0)

        snapshot = metrics.get_latency_metrics("defillama", window_hours=24)
        assert snapshot.total_runs == 2
        assert snapshot.success_runs == 1
        assert snapshot.failed_runs == 1
        assert snapshot.success_rate == 0.5

    def test_latency_percentiles(self, metrics):
        now = datetime.now(UTC)
        for ms in [100, 200, 300, 400, 500]:
            started = now
            finished = now + timedelta(milliseconds=ms)
            _insert_collection_log(metrics._get_conn(), "defillama", "success", started, finished, 1, 0)

        snapshot = metrics.get_latency_metrics("defillama", window_hours=24)
        assert snapshot.avg_latency_ms == 300.0
        assert snapshot.p95_latency_ms == 500.0


class TestFreshness:
    def test_freshness_minutes(self, metrics):
        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "success", now.isoformat())

        freshness = metrics.get_freshness("defillama")
        assert freshness is not None
        assert freshness < 1.0

    def test_freshness_none_when_no_sync(self, metrics):
        assert metrics.get_freshness("unknown") is None

    def test_freshness_overall_spans_all_sources(self, metrics):
        # Regression: get_freshness(None) previously queried a non-existent
        # 'all_sources' row and always returned None, so the overall snapshot's
        # freshness alert could never fire. None must now mean "across sources".
        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "success", (now - timedelta(minutes=30)).isoformat())
        _insert_source(metrics._get_conn(), "github", "success", now.isoformat())

        overall = metrics.get_freshness(None)
        assert overall is not None
        # Freshest successful sync wins (github at ~0 min, not defillama at ~30).
        assert overall < 1.0

    def test_freshness_overall_ignores_failed_syncs(self, metrics):
        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "error", now.isoformat())
        assert metrics.get_freshness(None) is None


class TestCoverageRate:
    def test_full_coverage(self, metrics):
        raw_data = '{"name": "LayerX", "url": "https://x.xyz", "sector": "L2", "stage": "testnet"}'
        _insert_raw_project(metrics._get_conn(), "defillama", raw_data)

        assert metrics.get_coverage_rate("defillama") == 1.0

    def test_partial_coverage(self, metrics):
        raw_data = '{"name": "LayerX"}'
        _insert_raw_project(metrics._get_conn(), "defillama", raw_data)

        assert metrics.get_coverage_rate("defillama") == 0.25

    def test_no_records_zero_coverage(self, metrics):
        assert metrics.get_coverage_rate("defillama") == 0.0


class TestDuplicateRate:
    def test_duplicate_rate(self, metrics):
        now = datetime.now(UTC)
        _insert_collection_log(metrics._get_conn(), "defillama", "success", now, now, 100, 30)

        assert metrics.get_duplicate_rate("defillama") == 0.3

    def test_no_logs_zero_duplicate_rate(self, metrics):
        assert metrics.get_duplicate_rate("defillama") == 0.0


class TestSourceMetrics:
    def test_full_snapshot(self, metrics):
        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "success", now.isoformat())
        _insert_collection_log(metrics._get_conn(), "defillama", "success", now, now, 10, 1)
        raw_data = '{"name": "LayerX", "url": "https://x.xyz", "sector": "L2", "stage": "testnet"}'
        _insert_raw_project(metrics._get_conn(), "defillama", raw_data)

        snapshot = metrics.get_source_metrics("defillama", window_hours=24)
        assert snapshot.source_id == "defillama"
        assert snapshot.success_rate == 1.0
        assert snapshot.coverage_rate == 1.0
        assert snapshot.duplicate_rate == 0.1


class TestCheckAlerts:
    def test_success_rate_alert(self, metrics):
        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "success", now.isoformat())
        # 1 success / 4 errors = 20% success rate
        _insert_collection_log(metrics._get_conn(), "defillama", "success", now, now, 1, 0)
        for _ in range(4):
            _insert_collection_log(metrics._get_conn(), "defillama", "error", now, now, 0, 0)

        alerts = metrics.check_alerts(window_hours=24)
        success_alerts = [a for a in alerts if a["metric"] == "success_rate"]
        assert len(success_alerts) == 1
        assert success_alerts[0]["source_id"] == "defillama"

    def test_freshness_alert(self, metrics):
        old = datetime.now(UTC) - timedelta(hours=3)
        _insert_source(metrics._get_conn(), "defillama", "success", old.isoformat())
        _insert_collection_log(metrics._get_conn(), "defillama", "success", old, old, 1, 0)

        alerts = metrics.check_alerts(window_hours=24)
        freshness_alerts = [a for a in alerts if a["metric"] == "freshness_minutes"]
        assert len(freshness_alerts) == 1


class TestDataQualityGauges:
    """check_alerts 顺手把数据质量 gauge 写进 Prometheus（OBSERVABILITY §9）。"""

    def test_check_alerts_sets_freshness_and_completeness(self, metrics):
        from app.metrics import DATA_COMPLETENESS_RATIO, DATA_FRESHNESS_SECONDS, metric_sample_value

        now = datetime.now(UTC)
        _insert_source(metrics._get_conn(), "defillama", "success", (now - timedelta(minutes=5)).isoformat())
        _insert_collection_log(metrics._get_conn(), "defillama", "success", now, now, 1, 0)
        raw_data = '{"name": "LayerX", "url": "https://x.xyz", "sector": "L2", "stage": "testnet"}'
        _insert_raw_project(metrics._get_conn(), "defillama", raw_data)

        metrics.check_alerts(window_hours=24)

        freshness = metric_sample_value(DATA_FRESHNESS_SECONDS, source_id="defillama")
        completeness = metric_sample_value(DATA_COMPLETENESS_RATIO, source_id="defillama")
        # ~5 分钟前同步 → 约 300 秒；留余量容忍时钟分辨率
        assert freshness >= 250.0
        assert completeness == 1.0

    def test_no_sync_leaves_freshness_unset(self, metrics):
        from app.metrics import DATA_COMPLETENESS_RATIO, metric_sample_value

        # 只有 source、没有成功同步 → freshness 不该被写成 0 或旧值，完整性照写
        _insert_source(metrics._get_conn(), "defillama", "error", None)
        metrics.check_alerts(window_hours=24)

        assert metric_sample_value(DATA_COMPLETENESS_RATIO, source_id="defillama") == 0.0
