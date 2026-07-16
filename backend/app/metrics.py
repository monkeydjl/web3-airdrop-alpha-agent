"""Application metrics for Prometheus.

Exposes a minimal set of RED/USE-style metrics for the Web3 Airdrop Alpha
Agent System. The /metrics endpoint renders these counters, histograms and
gauges in Prometheus exposition format.

Reference:
- docs/OBSERVABILITY.md §20
- docs/ENGINEERING_ROADMAP.md §20
"""

import structlog
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.config import settings

logger = structlog.get_logger(__name__)

# ── Pipeline metrics ──────────────────────────────────────────────
PIPELINE_RUNS = Counter(
    "airdrop_pipeline_runs_total",
    "Total number of scoring pipeline runs.",
    ["trigger"],
)

PIPELINE_DURATION = Histogram(
    "airdrop_pipeline_duration_seconds",
    "End-to-end pipeline duration in seconds.",
    buckets=[0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

PROJECTS_SCORED = Counter(
    "airdrop_projects_scored_total",
    "Total number of projects scored by the pipeline.",
)

PROJECTS_BY_LABEL = Counter(
    "airdrop_projects_by_label_total",
    "Projects scored grouped by final label.",
    ["label"],
)

# ── Collection metrics ──────────────────────────────────────────────
COLLECTION_RUNS = Counter(
    "airdrop_collection_runs_total",
    "Collection runs by source and final status.",
    ["source_id", "status"],
)

COLLECTION_DURATION = Histogram(
    "airdrop_collection_duration_seconds",
    "Collection duration by source.",
    ["source_id"],
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0],
)

COLLECTION_ITEMS = Counter(
    "airdrop_collection_items_total",
    "Raw items discovered per collection source.",
    ["source_id"],
)

COLLECTION_DUPLICATES = Counter(
    "airdrop_collection_duplicates_total",
    "Duplicate items per collection source.",
    ["source_id"],
)

# ── LLM metrics ─────────────────────────────────────────────────────
LLM_REQUESTS = Counter(
    "airdrop_llm_requests_total",
    "LLM API requests issued.",
    ["model"],
)

LLM_ERRORS = Counter(
    "airdrop_llm_errors_total",
    "LLM API request failures.",
    ["model"],
)

LLM_DURATION = Histogram(
    "airdrop_llm_duration_seconds",
    "LLM API request duration.",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

# ── Database / inventory gauges ───────────────────────────────────
DB_PROJECTS = Gauge(
    "airdrop_db_projects_total",
    "Number of scored projects currently in the database.",
)

DB_RAW_PROJECTS = Gauge(
    "airdrop_db_raw_projects_total",
    "Number of raw (auto-discovered) projects awaiting scoring.",
)

DB_COLLECTION_LOGS_24H = Gauge(
    "airdrop_db_collection_logs_24h_total",
    "Collection logs emitted in the last 24 hours.",
)


class MetricsExporter:
    """Render Prometheus metrics if metrics are enabled in settings."""

    @staticmethod
    def is_enabled() -> bool:
        return settings.metrics_enabled

    @staticmethod
    def content_type() -> str:
        return "text/plain; version=0.0.4; charset=utf-8"

    @staticmethod
    def render() -> bytes:
        return generate_latest()


def update_db_gauges(conn) -> None:
    """Refresh database gauges from the provided DB connection.

    The caller is responsible for handling connection lifecycle; this helper
    is intentionally narrow and swallows errors to avoid breaking pipelines.
    """
    from app.db import scalar

    try:
        project_count = scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone())
        DB_PROJECTS.set(project_count)

        raw_count = scalar(conn.execute("SELECT COUNT(*) FROM raw_projects WHERE processed_at IS NULL").fetchone())
        DB_RAW_PROJECTS.set(raw_count)

        log_count = scalar(
            conn.execute(
                "SELECT COUNT(*) FROM collection_logs WHERE started_at >= datetime('now', '-1 day')"
            ).fetchone()
        )
        DB_COLLECTION_LOGS_24H.set(log_count)
    except Exception:
        # Metrics are best-effort; never fail the request because of them.
        logger.exception("metrics.gauge_update_failed")
