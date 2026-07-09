"""Projects Query Endpoint - 查询项目列表.

GET /api/v1/projects
- 分页查询项目列表
- 按 score/label 筛选
- 按 sector/stage 筛选
- 排序支持

Reference:
- ENGINEERING_ROADMAP.md §8.2 查询端点
"""

from typing import Optional, List
from enum import Enum

from fastapi import APIRouter, Query, Path, HTTPException
from pydantic import BaseModel, Field, ConfigDict
import structlog

from app.openapi import PROJECTS_LIST_RESPONSE_EXAMPLE, ERROR_RESPONSE_EXAMPLES

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["projects"])


# ══════════════════════════════════════════════════════════════
# Enums and Models
# ══════════════════════════════════════════════════════════════

class SortBy(str, Enum):
    """排序字段枚举."""
    SCORE = "score"
    NAME = "name"
    CREATED_AT = "created_at"


class SortOrder(str, Enum):
    """排序顺序枚举."""
    ASC = "asc"
    DESC = "desc"


class ProjectListItem(BaseModel):
    """项目列表项（精简版）."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "layerx-001",
                "name": "LayerX",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
            }
        }
    )

    id: str
    name: str
    sector: Optional[str] = None
    stage: Optional[str] = None
    score: Optional[int] = None
    label: Optional[str] = None
    confidence: Optional[float] = None


class ProjectsResponse(BaseModel):
    """项目列表响应."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "projects": [
                        {
                            "id": "layerx-001",
                            "name": "LayerX",
                            "sector": "L2",
                            "score": 85,
                            "label": "FARM"
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20
                }
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="响应数据")


# ══════════════════════════════════════════════════════════════
# Endpoints
# ══════════════════════════════════════════════════════════════

@router.get(
    "/projects",
    response_model=ProjectsResponse,
    responses={
        200: {
            "description": "项目列表查询成功",
            "content": {
                "application/json": {
                    "example": PROJECTS_LIST_RESPONSE_EXAMPLE
                }
            }
        }
    },
    summary="查询项目列表",
    description=(
        "分页查询项目列表，支持按 score/label/sector 筛选和排序。\n\n"
        "## 查询参数\n\n"
        "- **分页**: page (页码), page_size (每页数量, 最大 100)\n"
        "- **筛选**: label (FARM/WATCH/IGNORE), sector, stage, min_score\n"
        "- **排序**: sort_by (score/name/created_at), sort_order (asc/desc)\n\n"
        "## MVP 限制\n\n"
        "当前版本返回空列表，V2 将连接数据库返回实际数据。\n\n"
        "## 示例\n\n"
        "```\n"
        "GET /api/v1/projects?label=FARM&min_score=70&sort_by=score&sort_order=desc\n"
        "```\n"
    ),
)
async def list_projects(
    page: int = Query(1, ge=1, description="页码（从1开始）"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    label: Optional[str] = Query(None, description="按标签筛选 (FARM/WATCH/IGNORE)"),
    sector: Optional[str] = Query(None, description="按赛道筛选"),
    stage: Optional[str] = Query(None, description="按阶段筛选"),
    min_score: Optional[int] = Query(None, ge=0, le=100, description="最低分数"),
    sort_by: SortBy = Query(SortBy.SCORE, description="排序字段"),
    sort_order: SortOrder = Query(SortOrder.DESC, description="排序顺序"),
) -> ProjectsResponse:
    """查询项目列表（MVP: 返回空列表，V2 将连接数据库）.

    Args:
        page: 页码
        page_size: 每页数量
        label: 标签筛选
        sector: 赛道筛选
        stage: 阶段筛选
        min_score: 最低分数
        sort_by: 排序字段
        sort_order: 排序顺序

    Returns:
        ProjectsResponse 包含项目列表
    """
    logger.info(
        "api.projects.list",
        page=page,
        page_size=page_size,
        label=label,
        sector=sector,
        stage=stage,
        min_score=min_score,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # MVP: 返回空列表
    # V2: 从数据库查询
    # projects = await db.query_projects(
    #     page=page,
    #     page_size=page_size,
    #     filters={...},
    #     sort_by=sort_by,
    #     sort_order=sort_order,
    # )

    return ProjectsResponse(
        ok=True,
        data={
            "projects": [],  # V2: 实际项目列表
            "total": 0,
            "page": page,
            "page_size": page_size,
            "filters": {
                "label": label,
                "sector": sector,
                "stage": stage,
                "min_score": min_score,
            },
            "sort": {
                "by": sort_by,
                "order": sort_order,
            }
        }
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {
                "application/json": {
                    "examples": {
                        "not_found": ERROR_RESPONSE_EXAMPLES["not_found"]
                    }
                }
            }
        }
    },
    summary="获取项目详情",
    description=(
        "根据项目 ID 获取完整项目信息。\n\n"
        "## MVP 限制\n\n"
        "当前版本返回 404，V2 将连接数据库返回实际项目详情。\n\n"
        "## 示例\n\n"
        "```\n"
        "GET /api/v1/projects/layerx-l2-001\n"
        "```\n"
    ),
)
async def get_project(
    project_id: str = Path(..., description="项目 ID"),
) -> ProjectsResponse:
    """获取单个项目详情（MVP: 返回 404，V2 将连接数据库）.

    Args:
        project_id: 项目 ID

    Returns:
        ProjectsResponse 包含项目详情

    Raises:
        HTTPException: 项目不存在
    """
    logger.info(
        "api.projects.get",
        project_id=project_id,
    )

    # MVP: 返回 404
    # V2: 从数据库查询
    # project = await db.get_project(project_id)
    # if not project:
    #     raise HTTPException(status_code=404, detail="Project not found")

    raise HTTPException(
        status_code=404,
        detail={
            "code": "NOT_FOUND",
            "message": f"Project {project_id} not found (database not implemented in MVP)"
        }
    )
