"""Participation / farm task checklist for a project."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Path

from app.repository import ProjectRepository
from app.services.participation_tasks import generate_participation_tasks
from app.services.project_signals import signals_view

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["participation"])


@router.get("/projects/{project_id}/participation-tasks")
def get_participation_tasks(
    project_id: str = Path(..., description="项目 ID"),
):
    """Return a prioritized checklist of things a user can do for this project."""
    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )

    # 必须走 signals_view：扩展信号存在 meta.signals 里，projects 表没有对应列，
    # 直接传 dict(project) 会让全部信号判断恒为 False（任务清单退化为通用套话）。
    data = generate_participation_tasks(signals_view(project))
    logger.info(
        "participation.tasks_generated",
        project_id=project_id,
        task_count=data.get("summary", {}).get("total"),
    )
    return {"ok": True, "data": data}
