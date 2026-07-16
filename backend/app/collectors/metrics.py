"""Collection quality metrics and alerting.

Implements collection health metrics:
- Success rate per source / overall
- Collection latency (p50/p95)
- Data freshness (time since last sync)
- Coverage rate (field completeness)
- Duplicate rate

Logs alerts when thresholds are breached.
Designed for Prometheus exposition later.

Reference:
- DATA_QUALITY.md §采集质量
- OBSERVABILITY.md §告警规则
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import get_connection

logger = structlog.get_logger(__name__)


@dataclass
class CollectionMetricsSnapshot:
    """Snapshot of collection health metrics."""

    source_id: str | None = None
    total_runs: int = 0
    success_runs: int = 0
    failed_runs: int = 0
    success_rate: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    last_sync_minutes_ago: float | None = None
    coverage_rate: float = 0.0
    duplicate_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "total_runs": self.total_runs,
            "success_runs": self.success_runs,
            "failed_runs": self.failed_runs,
            "success_rate": round(self.success_rate, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "last_sync_minutes_ago": (
                round(self.last_sync_minutes_ago, 2) if self.last_sync_minutes_ago is not None else None
            ),
            "coverage_rate": round(self.coverage_rate, 4),
            "duplicate_rate": round(self.duplicate_rate, 4),
        }


class CollectionMetrics:
    """Collection quality metrics calculator.

    Reads from collection_logs, data_sources, raw_projects tables.
    """

    def __init__(self, conn: Any | None = None):
        self._conn = conn

    def _get_conn(self):
        return self._conn if self._conn is not None else get_connection()

    def _should_close(self) -> bool:
        return self._conn is None

    def _execute(self, query: str, params: tuple = ()):
        conn = self._get_conn()
        try:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            if self._should_close():
                conn.close()

    def get_latency_metrics(
        self,
        source_id: str | None = None,
        window_hours: int = 24,
    ) -> CollectionMetricsSnapshot:
        """Calculate latency metrics from collection_logs."""
        params = []
        query = """
            SELECT
                started_at,
                finished_at,
                status
            FROM collection_logs
            WHERE started_at >= datetime('now', ?)
        """
        params.append(f"-{window_hours} hours")

        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        rows = self._execute(query, tuple(params))

        latencies = []
        success = 0
        failed = 0
        for row in rows:
            started = row.get("started_at")
            finished = row.get("finished_at")
            status = row.get("status")

            if status == "success":
                success += 1
            else:
                failed += 1

            if started and finished:
                try:
                    start_dt = datetime.fromisoformat(started)
                    finish_dt = datetime.fromisoformat(finished)
                    latency_ms = (finish_dt - start_dt).total_seconds() * 1000
                    latencies.append(latency_ms)
                except ValueError:
                    pass

        total = len(rows)
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        p95_latency = 0.0
        if latencies:
            sorted_latencies = sorted(latencies)
            idx = int(len(sorted_latencies) * 0.95)
            idx = min(idx, len(sorted_latencies) - 1)
            p95_latency = sorted_latencies[idx]

        return CollectionMetricsSnapshot(
            source_id=source_id,
            total_runs=total,
            success_runs=success,
            failed_runs=failed,
            success_rate=success / total if total > 0 else 0.0,
            avg_latency_ms=avg_latency,
            p95_latency_ms=p95_latency,
        )

    def get_freshness(self, source_id: str) -> float | None:
        """Return minutes since last successful sync for a source."""
        rows = self._execute(
            """
            SELECT last_sync
            FROM data_sources
            WHERE source_id = ? AND sync_status = 'success'
            ORDER BY last_sync DESC
            LIMIT 1
            """,
            (source_id,),
        )
        if not rows or not rows[0].get("last_sync"):
            return None

        try:
            last_sync = datetime.fromisoformat(rows[0]["last_sync"])
            if last_sync.tzinfo is None:
                last_sync = last_sync.replace(tzinfo=UTC)
            return (datetime.now(UTC) - last_sync).total_seconds() / 60.0
        except ValueError:
            return None

    def get_coverage_rate(self, source_id: str | None = None) -> float:
        """Calculate field coverage rate for raw_projects."""
        params = []
        query = """
            SELECT raw_data
            FROM raw_projects
            WHERE 1=1
        """
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        query += " LIMIT 1000"

        rows = self._execute(query, tuple(params))
        if not rows:
            return 0.0

        required_fields = ["name", "url", "sector", "stage"]
        total_score = 0.0
        for row in rows:
            raw_data = row.get("raw_data", "{}")
            try:
                import json

                data = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
            except json.JSONDecodeError:
                data = {}

            present = sum(1 for f in required_fields if data.get(f))
            total_score += present / len(required_fields)

        return total_score / len(rows)

    def get_duplicate_rate(self, source_id: str | None = None) -> float:
        """Calculate duplicate rate across collection logs."""
        params = []
        query = """
            SELECT
                SUM(items_collected) AS total,
                SUM(items_duplicate) AS duplicates
            FROM collection_logs
            WHERE status = 'success'
        """
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)

        rows = self._execute(query, tuple(params))
        if not rows:
            return 0.0

        total = rows[0].get("total") or 0
        duplicates = rows[0].get("duplicates") or 0
        if total == 0:
            return 0.0
        return duplicates / total

    def get_source_metrics(
        self,
        source_id: str,
        window_hours: int = 24,
    ) -> CollectionMetricsSnapshot:
        """Get full metrics snapshot for a single source."""
        snapshot = self.get_latency_metrics(source_id, window_hours)
        snapshot.last_sync_minutes_ago = self.get_freshness(source_id)
        snapshot.coverage_rate = self.get_coverage_rate(source_id)
        snapshot.duplicate_rate = self.get_duplicate_rate(source_id)
        return snapshot

    def get_overall_metrics(
        self,
        window_hours: int = 24,
    ) -> CollectionMetricsSnapshot:
        """Get overall metrics across all sources."""
        snapshot = self.get_latency_metrics(None, window_hours)
        snapshot.last_sync_minutes_ago = self.get_freshness("all_sources") or None
        snapshot.coverage_rate = self.get_coverage_rate(None)
        snapshot.duplicate_rate = self.get_duplicate_rate(None)
        return snapshot

    def check_alerts(self, window_hours: int = 24) -> list[dict[str, Any]]:
        """Check all sources for threshold breaches and log alerts.

        Returns:
            List of alert dicts
        """
        alerts: list[dict[str, Any]] = []
        thresholds = {
            "success_rate": 0.95,
            "avg_latency_ms": 30000.0,
            "freshness_minutes": 120.0,
            "coverage_rate": 0.5,
            "duplicate_rate": 0.5,
        }

        rows = self._execute("SELECT source_id FROM data_sources")
        source_ids = [row["source_id"] for row in rows]
        if not source_ids:
            source_ids = ["defillama", "github", "coingecko", "twitter_kol", "twitter_keyword"]

        for source_id in source_ids:
            snapshot = self.get_source_metrics(source_id, window_hours)

            if snapshot.success_rate < thresholds["success_rate"] and snapshot.total_runs > 0:
                alert = {
                    "source_id": source_id,
                    "metric": "success_rate",
                    "value": snapshot.success_rate,
                    "threshold": thresholds["success_rate"],
                    "severity": "warning",
                }
                alerts.append(alert)
                logger.warning("collection.alert", **alert)

            if snapshot.avg_latency_ms > thresholds["avg_latency_ms"]:
                alert = {
                    "source_id": source_id,
                    "metric": "avg_latency_ms",
                    "value": snapshot.avg_latency_ms,
                    "threshold": thresholds["avg_latency_ms"],
                    "severity": "warning",
                }
                alerts.append(alert)
                logger.warning("collection.alert", **alert)

            if (
                snapshot.last_sync_minutes_ago is not None
                and snapshot.last_sync_minutes_ago > thresholds["freshness_minutes"]
            ):
                alert = {
                    "source_id": source_id,
                    "metric": "freshness_minutes",
                    "value": snapshot.last_sync_minutes_ago,
                    "threshold": thresholds["freshness_minutes"],
                    "severity": "warning",
                }
                alerts.append(alert)
                logger.warning("collection.alert", **alert)

            if snapshot.coverage_rate < thresholds["coverage_rate"]:
                alert = {
                    "source_id": source_id,
                    "metric": "coverage_rate",
                    "value": snapshot.coverage_rate,
                    "threshold": thresholds["coverage_rate"],
                    "severity": "info",
                }
                alerts.append(alert)
                logger.info("collection.alert", **alert)

            if snapshot.duplicate_rate > thresholds["duplicate_rate"]:
                alert = {
                    "source_id": source_id,
                    "metric": "duplicate_rate",
                    "value": snapshot.duplicate_rate,
                    "threshold": thresholds["duplicate_rate"],
                    "severity": "warning",
                }
                alerts.append(alert)
                logger.warning("collection.alert", **alert)

        return alerts
