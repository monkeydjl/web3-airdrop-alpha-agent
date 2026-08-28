"""Watchlist Endpoints - 用户关注列表（ADR-008 V2）.

用户可以将感兴趣的项目加入 Watchlist，便于持续跟踪。
MVP 单用户模式：user_id 可选，缺省为 "default"。

Reference:
- ADR-008-user-system.md §3 行级数据隔离
- ENGINEERING_ROADMAP.md §展示与反馈
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.db import get_connection

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["watchlist"])

_DEFAULT_USER = "default"


# ═══════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════


class WatchlistAddRequest(BaseModel):
    """添加到 Watchlist 的请求。"""

    user_id: str | None = Field(None, max_length=64, description="用户标识（可选，MVP 缺省 default）")
    note: str | None = Field(None, max_length=500, description="用户备注")


class WatchlistResponse(BaseModel):
    """Watchlist 操作响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    ok: bool = False
    error: dict[str, str]


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/watchlist/{project_id}",
    response_model=WatchlistResponse,
    responses={
        404: {"model": ErrorResponse, "description": "项目不存在"},
        409: {"model": ErrorResponse, "description": "已在 Watchlist 中"},
    },
    summary="添加项目到 Watchlist",
    description="将指定项目加入用户的关注列表。已在列表中返回 409。",
)
def add_to_watchlist(
    body: WatchlistAddRequest,
    project_id: str = Path(..., description="项目 ID"),
) -> WatchlistResponse:
    """添加项目到 Watchlist。"""
    uid = body.user_id or _DEFAULT_USER

    try:
        with get_connection() as conn:
            # 检查项目是否存在
            row = conn.execute(
                "SELECT id, name FROM projects WHERE id = ?",
                (project_id,),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
                )

            # 检查是否已在 Watchlist
            existing = conn.execute(
                "SELECT id FROM watchlist WHERE project_id = ? AND user_id = ?",
                (project_id, uid),
            ).fetchone()
            if existing:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "ALREADY_WATCHED", "message": "Project already in watchlist"},
                )

            conn.execute(
                "INSERT INTO watchlist (project_id, user_id, note) VALUES (?, ?, ?)",
                (project_id, uid, body.note),
            )
            conn.commit()

        logger.info(
            "watchlist.added",
            project_id=project_id,
            user_id=uid,
        )

        return WatchlistResponse(
            data={
                "project_id": project_id,
                "user_id": uid,
                "action": "added",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("watchlist.add_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to add to watchlist"},
        ) from e


@router.delete(
    "/watchlist/{project_id}",
    response_model=WatchlistResponse,
    responses={
        404: {"model": ErrorResponse, "description": "不在 Watchlist 中"},
    },
    summary="从 Watchlist 移除项目",
    description="将指定项目从用户的关注列表中移除。",
)
def remove_from_watchlist(
    project_id: str = Path(..., description="项目 ID"),
    user_id: str | None = Query(None, description="用户标识（可选）"),
) -> WatchlistResponse:
    """从 Watchlist 移除项目。"""
    uid = user_id or _DEFAULT_USER

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM watchlist WHERE project_id = ? AND user_id = ?",
                (project_id, uid),
            )
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_IN_WATCHLIST", "message": "Project not in watchlist"},
                )
            conn.commit()

        logger.info(
            "watchlist.removed",
            project_id=project_id,
            user_id=uid,
        )

        return WatchlistResponse(
            data={
                "project_id": project_id,
                "user_id": uid,
                "action": "removed",
            }
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("watchlist.remove_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to remove from watchlist"},
        ) from e


@router.get(
    "/watchlist",
    response_model=WatchlistResponse,
    summary="查询 Watchlist",
    description="返回用户关注的项目列表，包含项目评分信息。",
)
def list_watchlist(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=200, description="每页数量"),
    user_id: str | None = Query(None, description="用户标识（可选）"),
) -> WatchlistResponse:
    """查询 Watchlist 列表。"""
    uid = user_id or _DEFAULT_USER

    try:
        with get_connection() as conn:
            # 总数
            total_row = conn.execute(
                "SELECT COUNT(*) FROM watchlist WHERE user_id = ?",
                (uid,),
            ).fetchone()
            total = int(total_row[0]) if total_row else 0

            # 分页查询，JOIN projects 获取评分信息
            offset = (page - 1) * page_size
            rows = conn.execute(
                """
                SELECT w.project_id, w.note, w.created_at AS watchlisted_at,
                       p.name, p.sector, p.stage, p.score, p.label, p.confidence,
                       p.url
                FROM watchlist w
                LEFT JOIN projects p ON p.id = w.project_id
                WHERE w.user_id = ?
                ORDER BY w.created_at DESC
                LIMIT ? OFFSET ?
                """,
                (uid, page_size, offset),
            ).fetchall()

            items = [
                {
                    "project_id": row["project_id"],
                    "name": row["name"] if "name" in row.keys() else None,
                    "sector": row["sector"] if "sector" in row.keys() else None,
                    "stage": row["stage"] if "stage" in row.keys() else None,
                    "score": row["score"] if "score" in row.keys() else None,
                    "label": row["label"] if "label" in row.keys() else None,
                    "confidence": row["confidence"] if "confidence" in row.keys() else None,
                    "url": row["url"] if "url" in row.keys() else None,
                    "note": row["note"],
                    "watchlisted_at": str(row["watchlisted_at"]) if row["watchlisted_at"] else None,
                }
                for row in rows
            ]

        return WatchlistResponse(
            data={
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
                "user_id": uid,
            }
        )
    except Exception as e:
        logger.error("watchlist.list_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to list watchlist"},
        ) from e
