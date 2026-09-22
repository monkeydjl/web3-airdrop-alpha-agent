"""Project Comparison Router (重点项目多维对比与竞品 PK 路由).

GET /api/v1/projects/compare?ids=proj1,proj2
"""

from typing import Any
from fastapi import APIRouter, HTTPException, Query
import structlog

from app.services.project_comparison import compare_projects

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/projects", tags=["comparison"])


@router.get("/compare", summary="多项目 8 维指标深度对比与竞品 PK 矩阵")
def get_comparison(
    ids: str = Query(..., description="待对比的项目 ID 列表，以逗号分隔，如 'proj1,proj2'"),
) -> dict[str, Any]:
    """横向比对选定项目的 8 维数据、雷达图对齐与差异化决策偏好."""
    project_ids = [i.strip() for i in ids.split(",") if i.strip()]
    if not project_ids:
        raise HTTPException(status_code=400, detail="Must provide at least one project id")

    try:
        data = compare_projects(project_ids)
        return data
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("api.projects.compare_failed", ids=ids, error=str(e), exc_info=True)
        raise HTTPException(status_code=500, detail=f"Comparison failed: {e}")
