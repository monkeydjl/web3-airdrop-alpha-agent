"""Collection Endpoints - 自动采集管理.

提供外部数据源采集任务的触发、状态查询、自动发现项目查询.

参考:
- API_SPEC.md §16-21 采集相关端点
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel, Field

from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.defillama import DefiLlamaCollector
from app.collectors.etherscan import EtherscanCollector
from app.collectors.galxe import GalxeCollector
from app.collectors.github import GitHubCollector
from app.collectors.layer3 import Layer3Collector
from app.collectors.persistence import CollectionRepository
from app.collectors.registry import CollectorRegistry
from app.collectors.twitter import TwitterKeywordCollector, TwitterKolCollector
from app.config import settings

router = APIRouter(tags=["collection"])


class DiscoveriesResponse(BaseModel):
    """自动发现项目列表响应。"""

    ok: bool = True
    data: dict = Field(..., description="包含 items / total / page / page_size")


class CollectionSourcesResponse(BaseModel):
    """数据源列表响应。"""

    ok: bool = True
    data: dict = Field(..., description="包含 sources 列表")


class CollectionTriggerResponse(BaseModel):
    """手动触发采集响应。"""

    ok: bool = True
    data: dict = Field(..., description="包含 source_id / status / items_collected")


def _build_registry() -> CollectorRegistry:
    """构建默认注册表 (包含已启用采集源)."""
    registry = CollectorRegistry()
    registry.register(DefiLlamaCollector())
    registry.register(GitHubCollector())
    registry.register(CoinGeckoCollector())
    registry.register(CryptoRankCollector())
    registry.register(TwitterKolCollector())
    registry.register(TwitterKeywordCollector())
    registry.register(EtherscanCollector())
    registry.register(GalxeCollector())
    registry.register(Layer3Collector())
    return registry


@router.get("/discoveries", response_model=DiscoveriesResponse)
async def list_discoveries(
    page: int = 1,
    page_size: int = 20,
    processed: bool | None = None,
    min_score: float = 0.0,
) -> DiscoveriesResponse:
    """查询自动发现项目 (raw_projects 表)."""
    repo = CollectionRepository()
    conn = repo._get_conn()
    try:
        if processed is None:
            count_query = "SELECT COUNT(*) FROM raw_projects WHERE discovery_score >= ?"
            count_params = [min_score]
            query = """
                SELECT raw_id, source_id, dedup_key, raw_data, discovered_at,
                       discovery_score, processed, project_id
                FROM raw_projects
                WHERE discovery_score >= ?
                ORDER BY discovery_score DESC, discovered_at DESC
                LIMIT ? OFFSET ?
            """
            query_params = [min_score]
        else:
            processed_flag = 1 if processed else 0
            count_query = "SELECT COUNT(*) FROM raw_projects WHERE discovery_score >= ? AND processed = ?"
            count_params = [min_score, processed_flag]
            query = """
                SELECT raw_id, source_id, dedup_key, raw_data, discovered_at,
                       discovery_score, processed, project_id
                FROM raw_projects
                WHERE discovery_score >= ? AND processed = ?
                ORDER BY discovery_score DESC, discovered_at DESC
                LIMIT ? OFFSET ?
            """
            query_params = [min_score, processed_flag]

        total = conn.execute(count_query, count_params).fetchone()[0]

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


@router.get("/collections/sources", response_model=CollectionSourcesResponse)
async def list_collection_sources() -> CollectionSourcesResponse:
    """列出已注册的采集源及其状态。"""
    registry = _build_registry()
    repo = CollectionRepository()
    conn = repo._get_conn()
    try:
        sources = []
        for collector in registry.list_all():
            source_id = collector.source_id
            # 查询 data_sources 表状态
            row = conn.execute(
                "SELECT enabled, sync_status, last_sync, api_calls_today FROM data_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()

            if row:
                status = {
                    "enabled": bool(row["enabled"]),
                    "sync_status": row["sync_status"],
                    "last_sync": row["last_sync"],
                    "api_calls_today": row["api_calls_today"],
                }
            else:
                status = {
                    "enabled": collector.is_enabled(),
                    "sync_status": "not_registered",
                    "last_sync": None,
                    "api_calls_today": 0,
                }

            sources.append(
                {
                    "source_id": source_id,
                    "source_name": collector.source_name,
                    "source_type": collector.source_type,
                    "is_enabled": collector.is_enabled(),
                    "status": status,
                }
            )

        return CollectionSourcesResponse(
            ok=True,
            data={"sources": sources},
        )
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
            detail={"code": "SOURCE_DISABLED", "message": f"Source {source_id} is disabled"},
        )

    result = await collector.collect()

    # 持久化到 raw_projects
    repo = CollectionRepository()
    repo.persist_collection_result(
        result,
        source_type=collector.source_type,
        source_name=collector.source_name,
    )

    auto_run: dict | None = None
    if settings.collection_auto_run_enabled and result.status in ("success", "partial"):
        from app.pipeline_run import execute_analysis_pipeline

        auto_run = await execute_analysis_pipeline(trigger="collection_auto")

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
        },
    )
