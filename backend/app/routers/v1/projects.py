"""Projects Query Endpoint - 查询项目列表.

GET /api/v1/projects
- 分页查询项目列表
- 按 score/label 筛选
- 按 sector/stage 筛选
- 排序支持

Reference:
- ENGINEERING_ROADMAP.md §8.2 查询端点
"""

from enum import StrEnum

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.openapi import ERROR_RESPONSE_EXAMPLES, PROJECTS_LIST_RESPONSE_EXAMPLE
from app.repository import ProjectRepository

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["projects"])


# ══════════════════════════════════════════════════════════════
# Enums and Models
# ══════════════════════════════════════════════════════════════


class SortBy(StrEnum):
    """排序字段枚举."""

    SCORE = "score"
    NAME = "name"
    CREATED_AT = "created_at"


class SortOrder(StrEnum):
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
    sector: str | None = None
    stage: str | None = None
    score: int | None = None
    label: str | None = None
    confidence: float | None = None


class ProjectsResponse(BaseModel):
    """项目列表响应."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "projects": [{"id": "layerx-001", "name": "LayerX", "sector": "L2", "score": 85, "label": "FARM"}],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                },
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
            "content": {"application/json": {"example": PROJECTS_LIST_RESPONSE_EXAMPLE}},
        }
    },
    summary="查询项目列表",
    description=(
        "分页查询项目列表，支持按 score/label/sector 筛选和排序。\n\n"
        "## 查询参数\n\n"
        "- **分页**: page (页码), page_size (每页数量, 最大 500)\n"
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
    page_size: int = Query(20, ge=1, le=500, description="每页数量"),
    label: str | None = Query(None, description="按标签筛选 (FARM/WATCH/IGNORE)"),
    sector: str | None = Query(None, description="按赛道筛选"),
    stage: str | None = Query(None, description="按阶段筛选"),
    min_score: int | None = Query(None, ge=0, le=100, description="最低分数"),
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

    # Query from database
    try:
        repo = ProjectRepository()
        db_projects, total = repo.list_projects(
            page=page,
            page_size=page_size,
            label=label,
            sector=sector,
            stage=stage,
            min_score=min_score,
            sort_by=sort_by.value,
            sort_order=sort_order.value,
        )

        # Convert to response format
        projects = [
            {
                "id": p["id"],
                "name": p["name"],
                "sector": p["sector"],
                "stage": p["stage"],
                "score": p["score"],
                "label": p["label"],
                "confidence": p["confidence"],
            }
            for p in db_projects
        ]

    except Exception as e:
        logger.error(
            "api.projects.list_failed",
            error=str(e),
            exc_info=True,
        )
        # Return empty on error (graceful degradation)
        projects = []
        total = 0

    return ProjectsResponse(
        ok=True,
        data={
            "projects": projects,
            "total": total,
            "page": page,
            "page_size": page_size,
            "filters": {
                "label": label,
                "sector": sector,
                "stage": stage,
                "min_score": min_score,
            },
            "sort": {
                "by": sort_by.value,
                "order": sort_order.value,
            },
        },
    )


@router.get(
    "/projects/{project_id}",
    response_model=ProjectsResponse,
    responses={
        404: {
            "description": "项目未找到",
            "content": {"application/json": {"examples": {"not_found": ERROR_RESPONSE_EXAMPLES["not_found"]}}},
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
    """获取单个项目详情.

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

    # Query from database
    try:
        repo = ProjectRepository()
        project = repo.get_by_id(project_id)

        if not project:
            raise HTTPException(
                status_code=404, detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"}
            )

        # Parse JSON fields (tolerate already-decoded values / bad rows)
        import json

        def _parse_json_field(value):
            if value is None or value == "":
                return None
            if isinstance(value, (dict, list)):
                return value
            try:
                return json.loads(value)
            except (TypeError, json.JSONDecodeError):
                return None

        narrative = _parse_json_field(project.get("narrative_json"))
        team = _parse_json_field(project.get("team_json"))
        risk = _parse_json_field(project.get("risk_json"))
        tokenomics = _parse_json_field(project.get("tokenomics_json"))
        reason = _parse_json_field(project.get("reason"))
        if reason is not None and not isinstance(reason, list):
            reason = [str(reason)]

        from app.services.project_signals import funding_public_view, parse_meta

        meta = parse_meta(project.get("meta"))
        funding = funding_public_view(project.get("meta"))
        signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}

        return {
            "ok": True,
            "data": {
                "project": {
                    "id": project["id"],
                    "name": project["name"],
                    "url": project.get("url"),
                    "sector": project.get("sector"),
                    "stage": project.get("stage"),
                    "score": project.get("score"),
                    "label": project.get("label"),
                    "confidence": project.get("confidence"),
                    "reason": reason or [],
                    "narrative": narrative or {},
                    "team": team or {},
                    "risk": risk or {},
                    "tokenomics": tokenomics or {},
                    "source": project.get("source"),
                    "funding": funding,
                    "signals": signals,
                    "funding_note": meta.get("funding_note"),
                    "created_at": str(project["created_at"]) if project.get("created_at") is not None else None,
                    "updated_at": str(project["updated_at"]) if project.get("updated_at") is not None else None,
                }
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.projects.get_failed",
            project_id=project_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500, detail={"code": "INTERNAL_ERROR", "message": f"Failed to retrieve project: {e!s}"}
        ) from e
