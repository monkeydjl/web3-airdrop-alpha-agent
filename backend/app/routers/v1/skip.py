"""Project skip endpoints — 用户自主「不参与」.

与 watchlist 同一套约定：匿名可写、按 body.user_id（缺省 'default'）隔离。
跳过只影响前端展示（工作台默认隐藏），不改项目本身的评分与标签。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.db import get_connection
from app.services.user_scope import DEFAULT_USER

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["skip"])


class SkipRequest(BaseModel):
    """请求体；user_id 不传走匿名默认用户（与 watchlist 同口径）。"""

    user_id: str | None = None


class SkipResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


def _project_exists(conn: Any, project_id: str) -> bool:
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row is not None


@router.post(
    "/projects/{project_id}/skip",
    response_model=SkipResponse,
    summary="标记项目为「不参与」",
)
def skip_project(project_id: str = Path(...), body: SkipRequest | None = None) -> SkipResponse:
    """标记项目为「不参与」。幂等：重复标记返回 already=True，不产生多行。"""
    uid = (body.user_id if body else None) or DEFAULT_USER

    try:
        with get_connection() as conn:
            if not _project_exists(conn, project_id):
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
                )

            existing = conn.execute(
                "SELECT id FROM project_skips WHERE project_id = ? AND user_id = ?",
                (project_id, uid),
            ).fetchone()
            if existing:
                return SkipResponse(
                    data={"project_id": project_id, "user_id": uid, "skipped": True, "already": True}
                )

            conn.execute(
                "INSERT INTO project_skips (project_id, user_id) VALUES (?, ?)",
                (project_id, uid),
            )
            conn.commit()

        logger.info("projects.skip_marked", project_id=project_id, user_id=uid)
        return SkipResponse(
            data={"project_id": project_id, "user_id": uid, "skipped": True, "already": False}
        )
    except HTTPException:
        raise
    except Exception as e:
        # 异常原文只进日志，不进响应体（可能带连接串/路径）。
        logger.error("projects.skip_mark_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to mark project as skipped"},
        ) from e


@router.delete(
    "/projects/{project_id}/skip",
    response_model=SkipResponse,
    summary="取消「不参与」标记",
)
def unskip_project(project_id: str = Path(...), user_id: str | None = None) -> SkipResponse:
    """取消「不参与」。项目没被标记过时返回 404。"""
    uid = user_id or DEFAULT_USER

    try:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM project_skips WHERE project_id = ? AND user_id = ?",
                (project_id, uid),
            ).fetchone()
            if not row:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "NOT_SKIPPED", "message": "Project is not skipped"},
                )
            conn.execute("DELETE FROM project_skips WHERE id = ?", (row[0],))
            conn.commit()

        logger.info("projects.skip_removed", project_id=project_id, user_id=uid)
        return SkipResponse(data={"project_id": project_id, "user_id": uid, "skipped": False})
    except HTTPException:
        raise
    except Exception as e:
        logger.error("projects.skip_remove_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to unmark project"},
        ) from e
