"""Application metrics for Prometheus.

Exposes a minimal set of RED/USE-style metrics for the Web3 Airdrop Alpha
Agent System. The /metrics endpoint renders these counters, histograms and
gauges in Prometheus exposition format.

Reference:
- docs/OBSERVABILITY.md §20
- docs/ENGINEERING_ROADMAP.md §20
"""

from collections.abc import Mapping
from typing import Any

import structlog
from prometheus_client import (
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

from app.config import settings
from app.db import DbConnection

logger = structlog.get_logger(__name__)
_MISSING = object()

# ── Pipeline metrics ──────────────────────────────────────────────
PIPELINE_RUNS = Counter(
    "airdrop_pipeline_runs_total",
    "Total number of scoring pipeline runs.",
    ["trigger", "status"],
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
OPPORTUNITY_ECONOMIC_SNAPSHOT_RESULTS = frozenset({"inserted", "duplicate", "schema_invalid", "skipped_flag_off"})
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


def metric_sample_value(metric: Any, **label_kwargs: str) -> float:
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


def metric_label_sets(metric: Any) -> frozenset[frozenset[tuple[str, str]]]:
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


# ── HTTP request metrics ─────────────────────────────────────────────
HTTP_REQUESTS = Counter(
    "airdrop_http_requests_total",
    "HTTP requests handled by the API.",
    ["method", "status_class"],
)


# ── LLM metrics ─────────────────────────────────────────────────────
#
# ⚠️ 这三个指标从注册那天起到 2026-08-24 之前**从来没有被 inc() 过一次** ——
# 声明了、暴露在 /metrics 里、被 OBSERVABILITY.md 记录、还有一条告警规则
# （HighLLMErrorRate）建立在其上，但没有任何递增点。
#
# **这比指标名写错更坏。** 名字写错时查询报不出数据，还有机会被发现；
# 一个存在但永不增长的指标，在面板上是一条平直的 0 线，在告警里是永不触发 ——
# 两者看起来都像"系统很健康"。值班的人以为有人盯着。
#
# 现在由 `app/llm/client.py` 在每次尝试后递增。
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

# ── LLM 成本与预算 ─────────────────────────────────────────────────
#
# 成本指标的特殊风险：**算错会被发现，算成 0 不会。**
# 所以除了金额本身，还要暴露"这笔账是怎么算出来的"（basis 标签）与
# "有多少次记账失败"—— 记账失败的花费永远不会计入预算，
# 累积起来就是预算静默失效。
LLM_COST_USD = Counter(
    "airdrop_llm_cost_usd_total",
    "Estimated LLM spend in USD (see app/llm/pricing.py for accuracy bounds).",
    ["model", "basis"],
)

LLM_TOKENS = Counter(
    "airdrop_llm_tokens_total",
    "LLM tokens consumed, split by direction.",
    ["model", "direction"],
)

LLM_BUDGET_BLOCKED = Counter(
    "airdrop_llm_budget_blocked_total",
    "LLM calls refused before dispatch, by reason.",
    ["reason"],
)

LLM_SPEND_RECORD_FAILURES = Counter(
    "airdrop_llm_spend_record_failures_total",
    "Ledger writes that failed after a paid LLM call (spend not counted toward budget).",
)

LLM_BUDGET_USD = Gauge(
    "airdrop_llm_budget_usd",
    "Configured LLM daily budget in USD (0 = unlimited).",
)

LLM_SPEND_TODAY_USD = Gauge(
    "airdrop_llm_spend_today_usd",
    "Estimated LLM spend for the current UTC day in USD.",
)

# 闭合词表：这两个标签的取值必须来自模块级常量，不允许运行时拼字符串。
# `basis` 与 `reason` 的真值分别定义在 app/llm/pricing.py 与 app/llm/budget.py，
# 由门禁比对两边一致。
LLM_TOKEN_DIRECTIONS: frozenset[str] = frozenset({"prompt", "completion"})


def record_llm_attempt(*, model: str, ok: bool, duration_seconds: float) -> None:
    """记录一次 LLM 尝试（成功或失败都算一次请求）。

    失败也计入 `LLM_REQUESTS`：错误率的分母必须是"尝试次数"，
    只统计成功的请求会让错误率算出大于 1 的值。
    """
    LLM_REQUESTS.labels(model=model).inc()
    if not ok:
        LLM_ERRORS.labels(model=model).inc()
    LLM_DURATION.observe(max(duration_seconds, 0.0))


def record_llm_cost(
    *,
    model: str,
    basis: str,
    cost_usd: float,
    prompt_tokens: int,
    completion_tokens: int,
) -> None:
    """记录一次调用的成本与 token 用量。"""
    LLM_COST_USD.labels(model=model, basis=basis).inc(max(cost_usd, 0.0))
    LLM_TOKENS.labels(model=model, direction="prompt").inc(max(prompt_tokens, 0))
    LLM_TOKENS.labels(model=model, direction="completion").inc(max(completion_tokens, 0))


def record_llm_budget_block(*, reason: str) -> None:
    """记录一次被预算拦下的调用。"""
    LLM_BUDGET_BLOCKED.labels(reason=reason).inc()


def record_llm_spend_record_failure() -> None:
    """记录一次记账失败（钱花了但没进账本）。"""
    LLM_SPEND_RECORD_FAILURES.inc()


def set_llm_budget_state(*, budget_usd: float, spent_today_usd: float) -> None:
    """刷新预算与当日花费 gauge。"""
    LLM_BUDGET_USD.set(max(budget_usd, 0.0))
    LLM_SPEND_TODAY_USD.set(max(spent_today_usd, 0.0))


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

# ── Competition cache metrics (ADR-010) ───────────────────────────
COMPETITION_CACHE_HITS = Counter(
    "airdrop_competition_cache_hits_total",
    "Competition sector count cache hits.",
)

COMPETITION_CACHE_MISSES = Counter(
    "airdrop_competition_cache_misses_total",
    "Competition sector count cache misses (triggers DB COUNT).",
)

COMPETITION_CACHE_DB_DURATION = Histogram(
    "airdrop_competition_cache_db_duration_seconds",
    "Time spent on DB COUNT(*) when cache misses.",
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
)

# ── Fetcher metrics (§10.1) ──────────────────────────────────────
FETCHER_CACHE_HITS = Counter(
    "airdrop_fetcher_cache_hits_total",
    "HTTP fetcher cache hits (in-memory or disk).",
)

FETCHER_CACHE_MISSES = Counter(
    "airdrop_fetcher_cache_misses_total",
    "HTTP fetcher cache misses (triggers network request).",
)

FETCHER_SEMAPHORE_USAGE = Gauge(
    "airdrop_concurrency_fetcher_semaphore_usage",
    "Current number of in-flight HTTP requests holding a fetcher semaphore slot.",
)

FETCHER_CIRCUIT_BREAKER_STATE = Gauge(
    "airdrop_fetcher_circuit_breaker_state",
    "Circuit breaker state: 0=CLOSED, 1=HALF_OPEN, 2=OPEN.",
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


def update_db_gauges(conn: DbConnection) -> None:
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
