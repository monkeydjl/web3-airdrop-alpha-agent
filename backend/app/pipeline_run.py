"""Shared analysis pipeline runner (handoff: /run + analysis cron + collection auto-run).

Reference: docs/COLLECTION_ANALYSIS_HANDOFF.md
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from math import floor
from typing import Any

import structlog

from app import tracing as _tracing
from app.agents.base import PipelineState, RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import run_orchestrator
from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.inflight import QUEUE_DRAIN_KEY, QueueDrainInProgressError, claim_run
from app.metrics import (
    PIPELINE_DURATION,
    PIPELINE_RUNS,
    PROJECTS_BY_LABEL,
    PROJECTS_SCORED,
    observe_opportunity_shadow_duration,
    record_opportunity_shadow_assessment,
    record_opportunity_shadow_projects,
    set_opportunity_shadow_rollout,
    update_db_gauges,
)
from app.opportunity.service import OpportunityService
from app.seed import get_seed_raw_projects
from app.utils.normalize import create_dedup_key

logger = structlog.get_logger(__name__)

OPPORTUNITY_SHADOW_EMPTY_STATS = {
    "eligible": 0,
    "sampled": 0,
    "attempted": 0,
    "saved": 0,
    "failed": 0,
    "skipped": 0,
}
OPPORTUNITY_SHADOW_BUCKETS = 10_000


def _record_shadow_metric(callback: Callable[..., Any], *args: Any) -> None:
    try:
        callback(*args)
    except Exception as error:
        logger.warning("pipeline.opportunity_shadow_metrics_failed", error=str(error))


def opportunity_shadow_bucket(project_id: str) -> int:
    digest = hashlib.sha256(project_id.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % OPPORTUNITY_SHADOW_BUCKETS


def is_opportunity_shadow_sampled(project_id: object, sample_rate: float) -> bool:
    if not isinstance(project_id, str) or not project_id.strip():
        return False
    threshold = floor(sample_rate * OPPORTUNITY_SHADOW_BUCKETS)
    return opportunity_shadow_bucket(project_id) < threshold


def run_opportunity_shadow(
    persisted_project_rows: list[dict[str, Any]],
    *,
    enabled: bool,
    sample_rate: float,
    service_factory: Callable[[], OpportunityService] | None = None,
) -> dict[str, int]:
    """Persist opportunity assessments without changing legacy pipeline state."""
    stats = OPPORTUNITY_SHADOW_EMPTY_STATS.copy()
    shadow_start = None
    try:
        if not enabled:
            return stats

        eligible_rows = [row for row in persisted_project_rows if row.get("score") is not None]
        stats["eligible"] = len(eligible_rows)
        sampled_rows = [row for row in eligible_rows if is_opportunity_shadow_sampled(row.get("id"), sample_rate)]
        stats["sampled"] = len(sampled_rows)
        stats["skipped"] = stats["eligible"] - stats["sampled"]
        if not sampled_rows:
            return stats

        shadow_start = time.perf_counter()
        service_factory = service_factory or OpportunityService
        try:
            service_context = service_factory()
        except Exception as error:
            logger.warning("pipeline.opportunity_shadow_lifecycle_failed", phase="constructor", error=str(error))
            return stats
        try:
            service = service_context.__enter__()
        except Exception as error:
            logger.warning("pipeline.opportunity_shadow_lifecycle_failed", phase="enter", error=str(error))
            return stats

        try:
            for row in sampled_rows:
                stats["attempted"] += 1
                try:
                    assessment = service.evaluate_row(row)
                    stats["saved"] += 1
                    _record_shadow_metric(record_opportunity_shadow_assessment, assessment)
                except Exception as error:
                    stats["failed"] += 1
                    logger.warning(
                        "pipeline.opportunity_shadow_failed",
                        project_id=row.get("id"),
                        error=str(error),
                    )
        finally:
            try:
                service_context.__exit__(None, None, None)
            except Exception as error:
                logger.warning("pipeline.opportunity_shadow_lifecycle_failed", phase="exit", error=str(error))
        return stats
    finally:
        _record_shadow_metric(record_opportunity_shadow_projects, stats)
        if stats["sampled"] > 0 and shadow_start is not None:
            _record_shadow_metric(observe_opportunity_shadow_duration, time.perf_counter() - shadow_start)


def mark_successful_raw_projects(
    raw_projects: list[RawProject],
    states: list[Any],
    repo: CollectionRepository | None = None,
    persisted_rows: list[dict[str, Any]] | None = None,
) -> int:
    """Mark raw_projects processed only for projects that actually reached the DB.

    出队即"这条原始记录不用再处理了"，因此判据必须是**落库成功**而不是内存里
    `state.score is not None`。此前只看内存分数：一旦持久化失败，项目既没写进
    `projects`、又被移出队列，数据永久丢失且无从发现。

    `persisted_rows` 为 None 时（调用方未落库，例如显式传入 projects 的路径）
    退回旧判据，保持既有行为不变。
    """
    repo = repo or CollectionRepository()
    if persisted_rows is None:
        success_ids = {s.project.id for s in states if getattr(s, "score", None) is not None}
    else:
        persisted_ids = {str(row.get("id")) for row in persisted_rows if row.get("id") is not None}
        success_ids = {
            s.project.id for s in states if getattr(s, "score", None) is not None and s.project.id in persisted_ids
        }
    marked = 0
    for raw_project in raw_projects:
        if raw_project.id not in success_ids:
            logger.info(
                "pipeline.mark_skip_failed",
                project_id=raw_project.id,
                name=raw_project.name,
            )
            continue
        if raw_project.raw_ids:
            for rid in raw_project.raw_ids:
                marked += repo.mark_raw_project_processed(
                    raw_id=rid,
                    project_id=raw_project.id,
                )
        else:
            dedup = create_dedup_key(raw_project.name, raw_project.sector).to_string()
            marked += repo.mark_raw_project_processed(
                project_id=raw_project.id,
                dedup_key=dedup,
            )
    logger.info("pipeline.mark_processed", marked=marked, success_count=len(success_ids))
    return marked


async def execute_analysis_pipeline(
    *,
    projects: list[RawProject] | None = None,
    enable_llm: bool = False,
    trigger: str = "manual",
    limit: int | None = None,
    save_to_db: bool = True,
) -> dict[str, Any]:
    """Run scoring pipeline from explicit projects or unprocessed raw_projects queue.

    Returns a dict suitable for RunResponse.data.

    队列排空路径（未显式传 projects）受进程内在飞守卫保护，重入时抛
    `QueueDrainInProgressError`；显式传入 projects 的路径不受限——它作用于调用方自带
    的数据，不共享队列，并发无害。守卫理由见 `app/inflight.py`。
    """
    if projects is not None and len(projects) > 0:
        try:
            return await _run_pipeline(
                projects=projects,
                enable_llm=enable_llm,
                trigger=trigger,
                limit=limit,
                save_to_db=save_to_db,
            )
        except Exception:
            PIPELINE_RUNS.labels(trigger=trigger, status="failed").inc()
            raise

    with claim_run(QUEUE_DRAIN_KEY) as acquired:
        if not acquired:
            logger.info("pipeline.queue_drain_rejected", trigger=trigger)
            raise QueueDrainInProgressError("An analysis queue drain is already in progress")
        try:
            return await _run_pipeline(
                projects=None,
                enable_llm=enable_llm,
                trigger=trigger,
                limit=limit,
                save_to_db=save_to_db,
            )
        except Exception:
            PIPELINE_RUNS.labels(trigger=trigger, status="failed").inc()
            raise


async def _run_pipeline(
    *,
    projects: list[RawProject] | None,
    enable_llm: bool,
    trigger: str,
    limit: int | None,
    save_to_db: bool,
) -> dict[str, Any]:
    """执行一次评分运行（无守卫；调用方负责在飞控制）。"""
    _record_shadow_metric(
        set_opportunity_shadow_rollout,
        settings.opportunity_shadow_enabled,
        settings.opportunity_shadow_sample_rate,
    )
    PIPELINE_RUNS.labels(trigger=trigger, status="started").inc()
    start_time = time.perf_counter()

    raw_projects: list[RawProject]
    from_repository = False
    if projects is not None and len(projects) > 0:
        raw_projects = projects
    else:
        from_repository = True
        collector = CollectorAgent()
        raw_projects = collector.collect_from_repository(
            CollectionRepository(),
            min_discovery_score=settings.discovery_score_analysis_threshold,
            limit=limit if limit is not None else settings.analysis_run_limit,
        )

    # §10.2 降级兜底：外部采集源全挂时回退到内置 seed 数据
    if not raw_projects and from_repository and settings.seed_fallback_enabled:
        logger.warning("pipeline.seed_fallback_activated", trigger=trigger)
        raw_projects = get_seed_raw_projects()
        # seed 数据无 raw_ids，不走 mark_processed 出队路径
        from_repository = False

    if not raw_projects:
        run_id = f"api-run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
        logger.info(
            "pipeline.opportunity_shadow_completed",
            run_id=run_id,
            **OPPORTUNITY_SHADOW_EMPTY_STATS,
        )
        return {
            "run_id": run_id,
            "status": "completed",
            "project_count": 0,
            "scored_count": 0,
            "error_count": 0,
            "top_score": None,
            "top_projects": [],
            "message": "No projects to score. Run a collector first or provide projects.",
            "marked_processed": 0,
            "opportunity_shadow": OPPORTUNITY_SHADOW_EMPTY_STATS.copy(),
        }

    run_id = f"api-run-{datetime.now(UTC).strftime('%Y%m%d-%H%M%S-%f')}"
    with _tracing.tracer.start_as_current_span("airdrop.pipeline.run") as span:
        span.set_attribute("run_id", run_id)
        span.set_attribute("trigger", trigger)
        span.set_attribute("project_count", len(raw_projects))

        response = await run_orchestrator(
            projects=raw_projects,
            run_id=run_id,
            enable_llm=enable_llm,
            save_to_db=save_to_db,
        )
    marked = 0
    if from_repository:
        # 只有真正写进 projects 的项目才允许出队（save_to_db=False 时不落库，
        # 传 None 退回"评分成功即出队"的旧判据）
        marked = mark_successful_raw_projects(
            raw_projects,
            response.states,
            persisted_rows=response.persisted_project_rows if save_to_db else None,
        )

    duration = time.perf_counter() - start_time
    PIPELINE_DURATION.observe(duration)
    # 只计入真正评分成功的项目，避免把 score=None 的失败态也计数（与 scored_count 一致）
    PROJECTS_SCORED.inc(sum(1 for s in response.states if s.score is not None))
    for state in response.states:
        if state.label:
            PROJECTS_BY_LABEL.labels(label=state.label).inc()

    try:
        from app.db import get_connection

        with get_connection() as conn:
            update_db_gauges(conn)
    except Exception as e:
        logger.warning("pipeline.gauge_update_failed", error=str(e))

    top_projects = _build_top_projects(response.states)
    logger.info(
        "pipeline.completed",
        run_id=response.run_id,
        status=response.status,
        project_count=response.project_count,
        marked_processed=marked,
        trigger=trigger,
        duration_seconds=duration,
    )

    opportunity_shadow = OPPORTUNITY_SHADOW_EMPTY_STATS.copy()
    if save_to_db and settings.opportunity_shadow_enabled:
        opportunity_shadow = await asyncio.to_thread(
            run_opportunity_shadow,
            response.persisted_project_rows,
            enabled=True,
            sample_rate=settings.opportunity_shadow_sample_rate,
        )
    logger.info(
        "pipeline.opportunity_shadow_completed",
        run_id=response.run_id,
        **opportunity_shadow,
    )

    result = {
        "run_id": response.run_id,
        "status": response.status,
        "project_count": response.project_count,
        "scored_count": len([s for s in response.states if s.score is not None]),
        "error_count": len(response.errors),
        "persisted_count": len(response.persisted_project_rows),
        "top_score": response.top_score,
        "top_projects": top_projects,
        "marked_processed": marked,
        "opportunity_shadow": opportunity_shadow,
    }
    record_pipeline_run(
        run_id=response.run_id,
        trigger=trigger,
        duration_ms=int(duration * 1000),
        summary=result,
        errors=response.errors,
    )
    PIPELINE_RUNS.labels(trigger=trigger, status="completed").inc()
    return result


def record_pipeline_run(
    *,
    run_id: str,
    trigger: str,
    duration_ms: int,
    summary: dict[str, Any],
    errors: list[dict[str, Any]] | None = None,
    error: str | None = None,
) -> None:
    """把每次运行落成一条持久记录。

    此前 `LogRepository.log_run` 定义了却从无调用方，且调度器把异常吞成一行日志，
    于是"整批数据静默丢失"这种故障在 DB 与 metrics 里都查不到。写库失败不得影响
    主流程——运行本身已经结束了，记账失败只该记一行警告。
    """
    try:
        from app.repository import LogRepository

        LogRepository().log_run(
            run_id=run_id,
            agent_name="pipeline",
            input_data={"trigger": trigger},
            output_data={k: v for k, v in summary.items() if k != "top_projects"},
            error=error or (json.dumps(errors, ensure_ascii=False) if errors else None),
            duration_ms=duration_ms,
        )
    except Exception as exc:  # pragma: no cover - 记账失败不能拖垮运行
        logger.warning("pipeline.run_record_failed", run_id=run_id, error=str(exc))


def _build_top_projects(states: list[PipelineState]) -> list[dict[str, Any]]:
    top_projects = []
    # 按分数降序取前 10（原实现取输入前 10，与 API 文档“按分数排序”不符）
    ranked = sorted(
        states,
        key=lambda s: s.score if s.score is not None else float("-inf"),
        reverse=True,
    )
    for state in ranked[:10]:
        project_result: dict[str, Any] = {
            "id": state.project.id,
            "name": state.project.name,
            "sector": state.project.sector,
            "stage": state.project.stage,
            "score": state.score,
            "label": state.label,
            "confidence": state.confidence,
            "reason": state.reason,
        }
        if state.narrative:
            project_result["narrative"] = {
                "sector": state.narrative.sector,
                "stage": state.narrative.stage,
                "heat_score": state.narrative.heat_score,
                "timing": state.narrative.timing,
            }
        if state.team:
            project_result["team"] = {
                "team_score": state.team.team_score,
                "team_type": state.team.team_type,
                "team_flags": state.team.team_flags,
            }
        if state.risk:
            project_result["risk"] = {
                "token_risk": state.risk.token_risk,
                "unlock_pressure": state.risk.unlock_pressure,
                "risk_flags": state.risk.risk_flags,
            }
        if state.tokenomics:
            project_result["tokenomics"] = {
                "vc_share": state.tokenomics.vc_share,
                "team_share": state.tokenomics.team_share,
                "unlock_penalty": state.tokenomics.unlock_penalty,
            }
        if state.errors:
            project_result["errors"] = [
                {
                    "agent_name": err.agent_name,
                    "kind": err.kind,
                    "message": err.message,
                }
                for err in state.errors
            ]
        top_projects.append(project_result)
    return top_projects
