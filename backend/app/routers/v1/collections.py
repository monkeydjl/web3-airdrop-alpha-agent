"""Collection Endpoints - 自动采集管理.

提供外部数据源采集任务的触发、状态查询、自动发现项目查询.

参考:
- API_SPEC.md §16-21 采集相关端点
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.collectors.base import DataCollector
from app.collectors.factory import get_default_registry
from app.collectors.persistence import CollectionRepository
from app.collectors.registry import CollectorRegistry
from app.config import settings
from app.db import DbConnection, get_connection, scalar
from app.inflight import QueueDrainInProgressError, claim_run, collect_key

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["collection"])


class DiscoveriesResponse(BaseModel):
    """自动发现项目列表响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(..., description="包含 items / total / page / page_size")


class CollectionSourcesResponse(BaseModel):
    """数据源列表响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(..., description="包含 sources 列表")


class CollectionTriggerResponse(BaseModel):
    """手动触发采集响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(..., description="包含 source_id / status / items_collected")


class CollectionSourcePatchRequest(BaseModel):
    """更新采集源运行时开关。"""

    enabled: bool = Field(..., description="是否启用（写入 data_sources.enabled）")


class CollectionSourcePatchResponse(BaseModel):
    """采集源开关更新响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(..., description="包含 source_id / enabled / config_ready / is_enabled")


def _build_registry() -> CollectorRegistry:
    """返回共享的默认注册表。

    必须复用同一批采集器实例：限流器令牌桶是实例状态，每请求新建等于
    每次都拿满桶，手动触发端点将完全绕过出站限流。
    """
    return get_default_registry()


@router.get("/discoveries", response_model=DiscoveriesResponse)
def list_discoveries(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    processed: bool | None = None,
    min_score: float = Query(0.0, ge=0.0),
) -> DiscoveriesResponse:
    """查询自动发现项目 (raw_projects 表), LEFT JOIN projects 展示评分."""
    repo = CollectionRepository()
    conn = repo._get_conn()
    try:
        if processed is None:
            count_query = "SELECT COUNT(*) FROM raw_projects WHERE discovery_score >= ?"
            count_params = [min_score]
            query = """
                SELECT r.raw_id, r.source_id, r.dedup_key, r.raw_data, r.discovered_at,
                       r.discovery_score, r.processed, r.project_id,
                       p.score AS score, p.label AS label, p.confidence AS confidence,
                       p.sector AS scored_sector, p.stage AS scored_stage
                FROM raw_projects r
                LEFT JOIN projects p ON p.id = r.project_id
                WHERE r.discovery_score >= ?
                ORDER BY r.discovery_score DESC, r.discovered_at DESC
                LIMIT ? OFFSET ?
            """
            query_params = [min_score]
        else:
            processed_flag = 1 if processed else 0
            count_query = "SELECT COUNT(*) FROM raw_projects WHERE discovery_score >= ? AND processed = ?"
            count_params = [min_score, processed_flag]
            query = """
                SELECT r.raw_id, r.source_id, r.dedup_key, r.raw_data, r.discovered_at,
                       r.discovery_score, r.processed, r.project_id,
                       p.score AS score, p.label AS label, p.confidence AS confidence,
                       p.sector AS scored_sector, p.stage AS scored_stage
                FROM raw_projects r
                LEFT JOIN projects p ON p.id = r.project_id
                WHERE r.discovery_score >= ? AND r.processed = ?
                ORDER BY r.discovery_score DESC, r.discovered_at DESC
                LIMIT ? OFFSET ?
            """
            query_params = [min_score, processed_flag]

        total = int(scalar(conn.execute(count_query, count_params).fetchone()) or 0)

        offset = (page - 1) * page_size
        query_params.extend([page_size, offset])
        rows = conn.execute(query, query_params).fetchall()

        items = []
        for row in rows:
            raw_data = row["raw_data"]
            try:
                import json

                raw_data_dict = json.loads(raw_data) if raw_data else {}
            except Exception:
                raw_data_dict = {}

            items.append(
                {
                    "raw_id": row["raw_id"],
                    "source_id": row["source_id"],
                    "dedup_key": row["dedup_key"],
                    "project_id": row["project_id"],
                    "name": raw_data_dict.get("name", ""),
                    "sector": raw_data_dict.get("sector"),
                    "stage": raw_data_dict.get("stage"),
                    "discovery_score": row["discovery_score"],
                    "processed": bool(row["processed"]),
                    "discovered_at": row["discovered_at"],
                    "score": row["score"] if "score" in row.keys() else None,
                    "label": row["label"] if "label" in row.keys() else None,
                    "confidence": row["confidence"] if "confidence" in row.keys() else None,
                }
            )

        return DiscoveriesResponse(
            ok=True,
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            },
        )
    finally:
        if repo._should_close():
            conn.close()


def _operator_enabled(conn: DbConnection, source_id: str) -> bool:
    """Runtime toggle from data_sources.enabled; missing row means enabled."""
    row = conn.execute(
        "SELECT enabled FROM data_sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    if row is None:
        return True
    return bool(row["enabled"])


def _source_payload(conn: DbConnection, collector: DataCollector) -> dict[str, Any]:
    """Build list/patch payload: config_ready ∧ operator_enabled → is_enabled."""
    source_id = collector.source_id
    config_ready = bool(collector.is_enabled())
    row = conn.execute(
        "SELECT enabled, sync_status, last_sync, api_calls_today FROM data_sources WHERE source_id = ?",
        (source_id,),
    ).fetchone()

    if row:
        operator_enabled = bool(row["enabled"])
        status = {
            "enabled": operator_enabled,
            "sync_status": row["sync_status"],
            "last_sync": row["last_sync"],
            "api_calls_today": row["api_calls_today"],
        }
    else:
        operator_enabled = True
        status = {
            "enabled": True,
            "sync_status": "not_registered",
            "last_sync": None,
            "api_calls_today": 0,
        }

    return {
        "source_id": source_id,
        "source_name": collector.source_name,
        "source_type": collector.source_type,
        "config_ready": config_ready,
        "operator_enabled": operator_enabled,
        "is_enabled": config_ready and operator_enabled,
        "status": status,
    }


@router.get("/collections/sources", response_model=CollectionSourcesResponse)
def list_collection_sources() -> CollectionSourcesResponse:
    """列出已注册的采集源及其状态。"""
    registry = _build_registry()
    repo = CollectionRepository()
    conn = repo._get_conn()
    try:
        sources = [_source_payload(conn, collector) for collector in registry.list_all()]
        return CollectionSourcesResponse(
            ok=True,
            data={"sources": sources},
        )
    finally:
        if repo._should_close():
            conn.close()


@router.patch(
    "/collections/{source_id}",
    response_model=CollectionSourcePatchResponse,
)
def patch_collection_source(
    body: CollectionSourcePatchRequest,
    source_id: str = Path(..., description="数据源 ID, 如 defillama"),
) -> CollectionSourcePatchResponse:
    """启用或禁用采集源（写入 data_sources.enabled，不影响 .env 配置能力位）。"""
    registry = _build_registry()
    collector = registry.get(source_id)
    if not collector:
        raise HTTPException(
            status_code=404,
            detail={"code": "SOURCE_NOT_FOUND", "message": f"Unknown source: {source_id}"},
        )

    repo = CollectionRepository()
    # Register row if missing (default enabled=1 via table default).
    repo.ensure_source(source_id, collector.source_type, collector.source_name)
    conn = repo._get_conn()
    try:
        conn.execute(
            """
            UPDATE data_sources
            SET enabled = ?, updated_at = CURRENT_TIMESTAMP
            WHERE source_id = ?
            """,
            (1 if body.enabled else 0, source_id),
        )
        conn.commit()
        payload = _source_payload(conn, collector)
        logger.info(
            "collections.source_toggled",
            source_id=source_id,
            enabled=body.enabled,
            is_enabled=payload["is_enabled"],
        )
        return CollectionSourcePatchResponse(ok=True, data=payload)
    finally:
        if repo._should_close():
            conn.close()


@router.post("/collections/{source_id}/trigger", response_model=CollectionTriggerResponse)
async def trigger_collection(
    source_id: str = Path(..., description="数据源 ID, 如 defillama"),
) -> CollectionTriggerResponse:
    """手动触发指定数据源采集。"""
    registry = _build_registry()
    collector = registry.get(source_id)
    if not collector:
        raise HTTPException(
            status_code=404,
            detail={"code": "SOURCE_NOT_FOUND", "message": f"Unknown source: {source_id}"},
        )

    if not collector.is_enabled():
        raise HTTPException(
            status_code=400,
            detail={
                "code": "SOURCE_CONFIG_DISABLED",
                "message": f"Source {source_id} is disabled in configuration (env/key)",
            },
        )

    repo_gate = CollectionRepository()
    conn_gate = repo_gate._get_conn()
    try:
        if not _operator_enabled(conn_gate, source_id):
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "SOURCE_DISABLED",
                    "message": f"Source {source_id} is disabled by operator",
                },
            )
    finally:
        if repo_gate._should_close() and conn_gate is not None:
            conn_gate.close()

    # 同一数据源同时只允许一次采集在飞：重复 POST（前端连点/重试）否则会各自
    # 发出真实出站请求、各自 persist。不同源之间不互斥。
    with claim_run(collect_key(source_id)) as acquired:
        if not acquired:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "COLLECTION_IN_PROGRESS",
                    "message": f"Collection for {source_id} is already running",
                },
            )

        conn = get_connection()
        try:
            result = await collector.collect()

            # 持久化到 raw_projects（request-scoped connection）
            repo = CollectionRepository(conn)
            repo.persist_collection_result(
                result,
                source_type=collector.source_type,
                source_name=collector.source_name,
            )

            # Economic path after successful persist only; failures must not alter response.
            try:
                from app.opportunity.economic_evidence import EconomicEvidenceEmitter
                from app.opportunity.economic_integration import (
                    manual_run_id,
                    process_persisted_collection,
                )
                from app.opportunity.economic_repository import EconomicSnapshotRepository
                from app.opportunity.economic_writer import EconomicSnapshotWriter
                from app.opportunity.repository import OpportunityRepository

                snap_repo = EconomicSnapshotRepository(conn)
                opp_repo = OpportunityRepository(conn)
                writer = EconomicSnapshotWriter(snap_repo)
                emitter = EconomicEvidenceEmitter(conn, snap_repo, opp_repo)
                process_persisted_collection(
                    result,
                    run_id=manual_run_id(),
                    writer=writer,
                    emitter=emitter,
                    settings_obj=settings,
                )
            except Exception as exc:
                logger.warning(
                    "collections.economic_failed",
                    source_id=source_id,
                    error_type=type(exc).__name__,
                    error=str(exc)[:200],
                )

            auto_run: dict[str, Any] | None = None
            auto_run_skipped: str | None = None
            if settings.collection_auto_run_enabled and result.status in ("success", "partial"):
                from app.pipeline_run import execute_analysis_pipeline

                try:
                    auto_run = await execute_analysis_pipeline(trigger="collection_auto")
                except QueueDrainInProgressError:
                    # 采集本身已成功落库，不因此报错：另一次排空正在跑，本批项目
                    # 会被后续运行取到（它们仍是 processed=0）。
                    auto_run_skipped = "queue_drain_in_progress"

            return CollectionTriggerResponse(
                ok=True,
                data={
                    "source_id": source_id,
                    "status": result.status,
                    "items_collected": len(result.items),
                    "items_new": result.items_new,
                    "items_duplicate": result.items_duplicate,
                    "started_at": result.started_at.isoformat() if result.started_at else None,
                    "finished_at": result.finished_at.isoformat() if result.finished_at else None,
                    "auto_run": auto_run,
                    "auto_run_skipped": auto_run_skipped,
                },
            )
        finally:
            conn.close()
