"""Participation / farm task checklist for a project."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Path

from app.repository import ProjectRepository
from app.services.participation_tasks import generate_participation_tasks

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["participation"])


@router.get("/projects/{project_id}/participation-tasks")
async def get_participation_tasks(
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

    data = generate_participation_tasks(dict(project))
    logger.info(
        "participation.tasks_generated",
        project_id=project_id,
        task_count=data.get("summary", {}).get("total"),
    )
    return {"ok": True, "data": data}
