"""归档运行历史与保留策略状态。

此前前端 `/archive` 页只能显示"暂无运行历史接口"：归档逻辑
（`app/archive.py`）是真的，但没有调度、没有运行记录、没有查询接口。
本路由提供只读的运行历史 + 当前各表的待归档规模。

只读端点，不触发归档 —— 手动触发请用 `scripts/archive_raw_data.py`，
它会以 `trigger=manual` 记入同一张历史表。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import settings
from app.db import DbConnection, get_connection, scalar
from app.repositories.archive_runs import ArchiveRunRepository

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["archive"])


class ArchiveRunsResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


def _cutoff(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days)).isoformat()


def _count(conn: DbConnection, sql: str, *params: Any) -> int:
    row = conn.execute(sql, params).fetchone()
    return int(scalar(row) or 0)


def _pending_snapshot(conn: DbConnection) -> list[dict[str, Any]]:
    """各档保留策略当前"够格被清理"的行数。

    这是给运维看"下一次跑会动多少行"的预估，与归档器用的是同一组条件。
    """
    return [
        {
            "key": "raw_processed",
            "table": "raw_projects",
            "label": "已立项的原始快照",
            "retention_days": settings.raw_projects_retention_days,
            "action": "archive",
            "total": _count(conn, "SELECT COUNT(*) FROM raw_projects WHERE processed = 1"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM raw_projects WHERE processed = 1 AND discovered_at < ?",
                _cutoff(settings.raw_projects_retention_days),
            ),
        },
        {
            "key": "raw_unprocessed",
            "table": "raw_projects",
            "label": "未过分析阈值的采集记录",
            "retention_days": settings.unprocessed_raw_retention_days,
            "action": "archive",
            "total": _count(conn, "SELECT COUNT(*) FROM raw_projects WHERE processed = 0"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM raw_projects WHERE processed = 0 AND discovered_at < ?",
                _cutoff(settings.unprocessed_raw_retention_days),
            ),
        },
        {
            "key": "signals",
            "table": "project_signals",
            "label": "信号与指标明细",
            "retention_days": settings.project_signals_retention_days,
            "action": "archive",
            "total": _count(conn, "SELECT COUNT(*) FROM project_signals"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM project_signals WHERE captured_at < ?",
                _cutoff(settings.project_signals_retention_days),
            ),
        },
        {
            "key": "logs",
            "table": "collection_logs",
            "label": "采集运行日志",
            "retention_days": settings.collection_logs_retention_days,
            "action": "delete",
            "total": _count(conn, "SELECT COUNT(*) FROM collection_logs"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM collection_logs WHERE started_at < ?",
                _cutoff(settings.collection_logs_retention_days),
            ),
        },
        {
            "key": "raw_archive",
            "table": "raw_projects_archive",
            "label": "原始快照归档表",
            "retention_days": settings.raw_archive_retention_days,
            "action": "delete",
            "total": _count(conn, "SELECT COUNT(*) FROM raw_projects_archive"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM raw_projects_archive WHERE archived_at < ?",
                _cutoff(settings.raw_archive_retention_days),
            ),
        },
        {
            "key": "signals_archive",
            "table": "project_signals_archive",
            "label": "信号归档表",
            "retention_days": settings.signals_archive_retention_days,
            "action": "delete",
            "total": _count(conn, "SELECT COUNT(*) FROM project_signals_archive"),
            "pending": _count(
                conn,
                "SELECT COUNT(*) FROM project_signals_archive WHERE archived_at < ?",
                _cutoff(settings.signals_archive_retention_days),
            ),
        },
    ]


@router.get(
    "/archive/runs",
    response_model=ArchiveRunsResponse,
    summary="归档运行历史",
    description=(
        "最近若干次归档运行（时间、触发方式、耗时、各分项行数、成功或失败），"
        "外加每档保留策略当前「够格被清理」的行数预估与调度配置。\n\n"
        "只读端点，不会触发归档。"
    ),
)
def get_archive_runs(
    limit: int = Query(20, ge=1, le=200, description="返回条数"),
) -> ArchiveRunsResponse:
    """返回归档运行历史 + 待清理规模 + 调度配置。"""
    try:
        with get_connection() as conn:
            repo = ArchiveRunRepository(conn)
            runs = repo.list_recent(limit=limit)
            counts = repo.counts()
            pending = _pending_snapshot(conn)
    except Exception as e:  # pragma: no cover - defensive
        logger.error("archive_runs.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to read archive runs"},
        ) from e

    return ArchiveRunsResponse(
        data={
            "runs": runs,
            "summary": {
                "total_runs": counts["total"],
                "failed_runs": counts["failed"],
                "last_run_at": runs[0]["started_at"] if runs else None,
                "pending_total": sum(int(p["pending"]) for p in pending),
            },
            "policies": pending,
            "schedule": {
                "enabled": settings.archive_scheduler_enabled,
                "cron": settings.archive_cron,
                "timezone": settings.timezone,
            },
        }
    )
