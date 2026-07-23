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

# ── Opportunity Economic metrics (closed vocabularies) ─────────────
OPPORTUNITY_ECONOMIC_SOURCES = frozenset({"defillama", "coingecko", "cryptorank"})
OPPORTUNITY_ECONOMIC_SNAPSHOT_RESULTS = frozenset(
    {"inserted", "duplicate", "schema_invalid", "skipped_flag_off"}
)
OPPORTUNITY_ECONOMIC_OBSERVATION_RESULTS = frozenset({"built", "skipped_no_snapshot"})
OPPORTUNITY_ECONOMIC_EVIDENCE_RESULTS = frozenset(
    {"emitted", "skipped_no_project", "duplicate", "skipped_flag_off", "content_conflict"}
)
OPPORTUNITY_ECONOMIC_IDENTITY_RESULTS = frozenset({"linked", "unlinked"})

OPPORTUNITY_ECONOMIC_SNAPSHOTS = Counter(
    "opportunity_economic_snapshots_total",
    "Opportunity economic snapshots by source and result.",
    ["source", "result"],
)

OPPORTUNITY_ECONOMIC_OBSERVATIONS = Counter(
    "opportunity_economic_observations_total",
    "Opportunity economic in-memory observations by source and result.",
    ["source", "result"],
)

OPPORTUNITY_ECONOMIC_EVIDENCE = Counter(
    "opportunity_economic_evidence_total",
    "Opportunity economic evidence emits by source and result.",
    ["source", "result"],
)

OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION = Counter(
    "opportunity_economic_identity_resolution_total",
    "Opportunity economic identity resolution by source and result.",
    ["source", "result"],
)

OPPORTUNITY_ECONOMIC_RUN_DURATION = Histogram(
    "opportunity_economic_run_duration_seconds",
    "Opportunity economic writer/process duration by source.",
    ["source"],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0],
)

OPPORTUNITY_ECONOMIC_LAST_SUCCESS = Gauge(
    "opportunity_economic_last_success_unixtime",
    "Unix time of last opportunity-economic process that built ≥1 observation.",
    ["source"],
)


def _require_economic_source(source: str) -> str:
    if source not in OPPORTUNITY_ECONOMIC_SOURCES:
        raise ValueError(f"illegal opportunity economic source: {source!r}")
    return source


def _require_closed_result(result: str, allowed: frozenset[str], *, kind: str) -> str:
    if result not in allowed:
        raise ValueError(f"illegal opportunity economic {kind} result: {result!r}")
    return result


def record_opportunity_economic_snapshot(*, source: str, result: str) -> None:
    """Inc snapshots counter after validating closed source/result vocabularies."""
    _require_economic_source(source)
    _require_closed_result(result, OPPORTUNITY_ECONOMIC_SNAPSHOT_RESULTS, kind="snapshot")
    OPPORTUNITY_ECONOMIC_SNAPSHOTS.labels(source=source, result=result).inc()


def record_opportunity_economic_observation(*, source: str, result: str) -> None:
    """Inc observations counter after validating closed source/result vocabularies."""
    _require_economic_source(source)
    _require_closed_result(result, OPPORTUNITY_ECONOMIC_OBSERVATION_RESULTS, kind="observation")
    OPPORTUNITY_ECONOMIC_OBSERVATIONS.labels(source=source, result=result).inc()


def record_opportunity_economic_evidence(*, source: str, result: str) -> None:
    """Inc evidence counter after validating closed source/result vocabularies (Task 5+)."""
    _require_economic_source(source)
    _require_closed_result(result, OPPORTUNITY_ECONOMIC_EVIDENCE_RESULTS, kind="evidence")
    OPPORTUNITY_ECONOMIC_EVIDENCE.labels(source=source, result=result).inc()


def record_opportunity_economic_identity(*, source: str, result: str) -> None:
    """Inc identity counter after validating closed source/result vocabularies (Task 5+)."""
    _require_economic_source(source)
    _require_closed_result(result, OPPORTUNITY_ECONOMIC_IDENTITY_RESULTS, kind="identity")
    OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION.labels(source=source, result=result).inc()


def observe_opportunity_economic_duration(*, source: str, duration_seconds: float) -> None:
    """Observe writer process duration after validating source vocabulary."""
    _require_economic_source(source)
    OPPORTUNITY_ECONOMIC_RUN_DURATION.labels(source=source).observe(duration_seconds)


def set_opportunity_economic_last_success(*, source: str, unixtime: float) -> None:
    """Set last-success gauge after validating source vocabulary."""
    _require_economic_source(source)
    OPPORTUNITY_ECONOMIC_LAST_SUCCESS.labels(source=source).set(unixtime)


def metric_sample_value(metric, **label_kwargs) -> float:
    """Read a Prometheus sample value by full label match.

    Inspects ``metric.collect()`` samples (Counter/Histogram/Gauge). Missing
    samples return ``0.0``. Prefer ``*_total`` (Counter), then Gauge name,
    then Histogram ``*_count`` / ``*_sum``. Skips ``*_created`` timestamps.

    Tests must use this (and :func:`metric_label_sets`) for value/delta
    assertions — bare ``Counter.labels()`` is invalid verification.
    """
    wanted = {str(k): str(v) for k, v in label_kwargs.items()}
    candidates: list[tuple[int, float]] = []
    for family in metric.collect():
        for sample in family.samples:
            name = sample.name
            if name.endswith("_created"):
                continue
            labels = {str(k): str(v) for k, v in sample.labels.items()}
            # Exact label match for non-histogram-bucket samples; buckets need le.
            if name.endswith("_bucket"):
                if "le" not in wanted:
                    continue
                if labels != wanted:
                    continue
            else:
                # Ignore extra 'le' not requested; require all wanted keys equal.
                if any(labels.get(k) != v for k, v in wanted.items()):
                    continue
                extra = set(labels) - set(wanted)
                if extra:
                    continue
            priority = 3
            if name.endswith("_total"):
                priority = 0
            elif not name.endswith(("_count", "_sum", "_bucket")):
                priority = 1  # gauge
            elif name.endswith("_count"):
                priority = 2
            elif name.endswith("_sum"):
                priority = 3
            candidates.append((priority, float(sample.value)))
    if not candidates:
        return 0.0
    candidates.sort(key=lambda item: item[0])
    return candidates[0][1]


def metric_label_sets(metric) -> frozenset[frozenset[tuple[str, str]]]:
    """Return closed label sets from metric samples (excluding ``*_created``).

    Each sample contributes ``frozenset`` of ``(label, value)`` pairs; the outer
    container is also a ``frozenset``. Bare ``Counter.labels()`` existence is
    not a substitute for this inspection.
    """
    sets: set[frozenset[tuple[str, str]]] = set()
    for family in metric.collect():
        for sample in family.samples:
            if sample.name.endswith("_created"):
                continue
            sets.add(frozenset((str(k), str(v)) for k, v in sample.labels.items()))
    return frozenset(sets)


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
