"""Application metrics for Prometheus.

Exposes a minimal set of RED/USE-style metrics for the Web3 Airdrop Alpha
Agent System. The /metrics endpoint renders these counters, histograms and
gauges in Prometheus exposition format.

Reference:
- docs/OBSERVABILITY.md §20
- docs/ENGINEERING_ROADMAP.md §20
"""

from collections.abc import Mapping

import structlog
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.config import settings

logger = structlog.get_logger(__name__)
_MISSING = object()

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

# ── Opportunity Shadow metrics ───────────────────────────────────
OPPORTUNITY_SHADOW_PROJECT_RESULTS = (
    "eligible",
    "sampled",
    "attempted",
    "saved",
    "failed",
    "skipped",
)

OPPORTUNITY_SHADOW_PROJECTS = Counter(
    "airdrop_opportunity_shadow_projects_total",
    "Automatic Opportunity Shadow projects by batch result.",
    ["result"],
)

OPPORTUNITY_SHADOW_ASSESSMENTS = Counter(
    "airdrop_opportunity_shadow_assessments_total",
    "Persisted Opportunity Shadow assessments by bounded model outcome.",
    ["status", "public_label", "model_version", "profile_version"],
)

OPPORTUNITY_SHADOW_DURATION = Histogram(
    "airdrop_opportunity_shadow_duration_seconds",
    "Automatic Opportunity Shadow selected-batch duration.",
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

OPPORTUNITY_SHADOW_ENABLED = Gauge(
    "airdrop_opportunity_shadow_enabled",
    "Whether automatic Opportunity Shadow evaluation is enabled.",
)

OPPORTUNITY_SHADOW_SAMPLE_RATE = Gauge(
    "airdrop_opportunity_shadow_sample_rate",
    "Configured deterministic Opportunity Shadow sample rate.",
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


def _assessment_metric_value(assessment: object, attribute: str) -> str:
    value = getattr(assessment, attribute, _MISSING)
    if value is _MISSING:
        return "unknown"
    enum_value = getattr(value, "value", _MISSING)
    return str(enum_value) if enum_value is not _MISSING else str(value)


def set_opportunity_shadow_rollout(enabled: bool, sample_rate: float) -> None:
    try:
        if not MetricsExporter.is_enabled():
            return
        OPPORTUNITY_SHADOW_ENABLED.set(1 if enabled else 0)
        OPPORTUNITY_SHADOW_SAMPLE_RATE.set(sample_rate)
    except Exception as error:
        logger.warning("metrics.opportunity_shadow_update_failed", error=str(error))


def record_opportunity_shadow_projects(stats: Mapping[str, int]) -> None:
    try:
        if not MetricsExporter.is_enabled():
            return
        for result in OPPORTUNITY_SHADOW_PROJECT_RESULTS:
            OPPORTUNITY_SHADOW_PROJECTS.labels(result=result).inc(stats.get(result, 0))
    except Exception as error:
        logger.warning("metrics.opportunity_shadow_update_failed", error=str(error))


def record_opportunity_shadow_assessment(assessment: object) -> None:
    try:
        if not MetricsExporter.is_enabled():
            return
        OPPORTUNITY_SHADOW_ASSESSMENTS.labels(
            status=_assessment_metric_value(assessment, "status"),
            public_label=_assessment_metric_value(assessment, "public_label"),
            model_version=_assessment_metric_value(assessment, "model_version"),
            profile_version=_assessment_metric_value(assessment, "profile_version"),
        ).inc()
    except Exception as error:
        logger.warning("metrics.opportunity_shadow_update_failed", error=str(error))


def observe_opportunity_shadow_duration(duration_seconds: float) -> None:
    try:
        if not MetricsExporter.is_enabled():
            return
        OPPORTUNITY_SHADOW_DURATION.observe(duration_seconds)
    except Exception as error:
        logger.warning("metrics.opportunity_shadow_update_failed", error=str(error))


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
