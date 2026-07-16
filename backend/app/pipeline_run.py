"""Shared analysis pipeline runner (handoff: /run + analysis cron + collection auto-run).

Reference: docs/COLLECTION_ANALYSIS_HANDOFF.md
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime
from math import floor
from typing import Any

import structlog

from app.agents.base import RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import run_orchestrator
from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.metrics import (
    PIPELINE_DURATION,
    PIPELINE_RUNS,
    PROJECTS_BY_LABEL,
    PROJECTS_SCORED,
    update_db_gauges,
)
from app.opportunity.service import OpportunityService
from app.utils.normalize import create_dedup_key

logger = structlog.get_logger(__name__)

OPPORTUNITY_SHADOW_EMPTY_STATS = {"attempted": 0, "saved": 0, "failed": 0}
OPPORTUNITY_SHADOW_BUCKETS = 10_000


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
    service_factory=None,
) -> dict[str, int]:
    """Persist opportunity assessments without changing legacy pipeline state."""
    stats = OPPORTUNITY_SHADOW_EMPTY_STATS.copy()
    if not enabled:
        return stats

    scored_rows = [row for row in persisted_project_rows if row.get("score") is not None]
    if not scored_rows:
        return stats

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
        for row in scored_rows:
            stats["attempted"] += 1
            try:
                service.evaluate_row(row)
                stats["saved"] += 1
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


def mark_successful_raw_projects(
    raw_projects: list[RawProject],
    states: list[Any],
    repo: CollectionRepository | None = None,
) -> int:
    """Mark raw_projects processed only for successfully scored projects.

    Success = state.score is not None. Uses raw_ids when present, else project_id/dedup_key.
    """
    repo = repo or CollectionRepository()
    success_ids = {s.project.id for s in states if getattr(s, "score", None) is not None}
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
            n = repo.mark_raw_project_processed(
                project_id=raw_project.id,
                dedup_key=dedup,
            )
            if n == 0:
                n = repo.mark_raw_project_processed(dedup_key=dedup, project_id=raw_project.id)
            marked += n
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
    """
    PIPELINE_RUNS.labels(trigger=trigger).inc()
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

    if not raw_projects:
        run_id = f"api-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
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

    run_id = f"api-run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    response = await run_orchestrator(
        projects=raw_projects,
        run_id=run_id,
        enable_llm=enable_llm,
        save_to_db=save_to_db,
    )
    marked = 0
    if from_repository:
        marked = mark_successful_raw_projects(raw_projects, response.states)

    duration = time.perf_counter() - start_time
    PIPELINE_DURATION.observe(duration)
    PROJECTS_SCORED.inc(len(response.states))
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
        )
    logger.info(
        "pipeline.opportunity_shadow_completed",
        run_id=response.run_id,
        **opportunity_shadow,
    )

    return {
        "run_id": response.run_id,
        "status": response.status,
        "project_count": response.project_count,
        "scored_count": len([s for s in response.states if s.score is not None]),
        "error_count": len(response.errors),
        "top_score": response.top_score,
        "top_projects": top_projects,
        "marked_processed": marked,
        "opportunity_shadow": opportunity_shadow,
    }


def _build_top_projects(states) -> list[dict]:
    top_projects = []
    for state in states[:10]:
        project_result = {
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
