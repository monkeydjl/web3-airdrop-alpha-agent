"""今日行动队列 —— 跨项目聚合的可执行清单。

评分决策引擎产出上百个 FARM/WATCH 项目后，此前没有任何视图回答「今天该做
什么」：参与清单只在单个项目详情页存在。本路由把它跨项目聚合并排序。

完成状态**复用 interactions 表**（不新建状态表），所以这里只提供读取；
标记「已做」走既有的 `POST /api/v1/interactions`。
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.db import get_connection
from app.repository import ProjectRepository
from app.services.action_queue import build_action_queue

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["action-queue"])

_DEFAULT_USER = "default"

# 候选池上限：行动队列只取前若干高分项目做候选，避免为了 5 条建议把
# 288 行全量 JSON 解析一遍。按 score 降序取样已足够覆盖 FARM/WATCH。
_CANDIDATE_POOL = 60


class ActionQueueResponse(BaseModel):
    ok: bool = True
    data: dict = Field(default_factory=dict)


def _engaged_project_ids(conn, user_id: str) -> set[str]:
    """已有交互记录的项目（含任何状态：planned/active/done 都算已跟进）。"""
    rows = conn.execute(
        "SELECT DISTINCT project_id FROM interactions WHERE user_id = ? OR user_id IS NULL",
        (user_id,),
    ).fetchall()
    return {str(r[0]) for r in rows if r and r[0]}


def _watchlisted_project_ids(conn, user_id: str) -> set[str]:
    rows = conn.execute(
        "SELECT DISTINCT project_id FROM watchlist WHERE user_id = ? OR user_id IS NULL",
        (user_id,),
    ).fetchall()
    return {str(r[0]) for r in rows if r and r[0]}


@router.get(
    "/action-queue",
    response_model=ActionQueueResponse,
    summary="今日行动清单",
    description=(
        "把 FARM/WATCH 项目的参与清单跨项目聚合，按「任务优先级 × 项目分数 × "
        "是否必做 × 是否已收藏」排序，默认排除已有交互记录的项目。\n\n"
        "这是只读聚合，不产生新评分；标记完成请调用 POST /api/v1/interactions。"
    ),
)
def get_action_queue(
    limit: int = Query(5, ge=1, le=50, description="返回条数"),
    per_project_limit: int = Query(2, ge=1, le=10, description="同一项目最多贡献几条"),
    include_engaged: bool = Query(False, description="是否包含已有交互记录的项目"),
    user_id: str | None = Query(None, max_length=64, description="用户标识（缺省 default）"),
) -> ActionQueueResponse:
    """返回一份有限、有序、可执行的今日行动清单。"""
    uid = user_id or _DEFAULT_USER
    repo = ProjectRepository()

    try:
        # 按分数降序取候选池；行动价值与项目分强相关，低分项目基本不会入选前 N。
        projects, _total = repo.list_projects(
            page=1,
            page_size=_CANDIDATE_POOL,
            sort_by="score",
            sort_order="desc",
        )

        with get_connection() as conn:
            engaged = _engaged_project_ids(conn, uid)
            watched = _watchlisted_project_ids(conn, uid)

        data = build_action_queue(
            projects,
            engaged_project_ids=engaged,
            watchlisted_project_ids=watched,
            limit=limit,
            per_project_limit=per_project_limit,
            include_engaged=include_engaged,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.error("action_queue.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to build action queue"},
        ) from e

    data["user_id"] = uid
    logger.info(
        "action_queue.built",
        user_id=uid,
        returned=data["summary"]["returned"],
        candidates=data["summary"]["candidates"],
        skipped_engaged=data["summary"]["projects_skipped_engaged"],
    )
    return ActionQueueResponse(data=data)
