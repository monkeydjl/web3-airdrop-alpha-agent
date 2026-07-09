"""Export and Import API endpoints.

提供导入导出功能:
- GET /api/v1/export/projects - 导出项目列表
- GET /api/v1/export/project/{id} - 导出单个项目详情
- GET /api/v1/export/template - 下载导入模板
- POST /api/v1/import/projects - 批量导入项目并评分
"""

from typing import Literal, Optional

from fastapi import APIRouter, Query, Path, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse, Response
import structlog

from app.repository import ProjectRepository
from app.export import (
    export_projects_to_excel,
    export_projects_to_csv,
    export_project_detail_to_excel,
)
from app.import_utils import (
    import_projects_from_excel,
    import_projects_from_csv,
    validate_imported_projects,
    create_import_template_excel,
)
from app.agents.orchestrator_simple import run_orchestrator
from app.agents.base import RawProject, AgentContext
from app.models import RunResponse
import io

router = APIRouter()
logger = structlog.get_logger(__name__)


@router.get(
    "/export/projects",
    summary="导出项目列表",
    description=(
        "导出项目列表到 Excel 或 CSV 格式。\n\n"
        "## 支持格式\n\n"
        "- `excel`: Excel (.xlsx) - 带样式和颜色标记\n"
        "- `csv`: CSV (.csv) - 纯文本格式\n\n"
        "## 筛选参数\n\n"
        "支持与 GET /projects 相同的筛选参数"
    ),
)
async def export_projects(
    format: Literal["excel", "csv"] = Query("excel", description="导出格式"),
    label: Optional[str] = Query(None, description="按标签筛选"),
    sector: Optional[str] = Query(None, description="按赛道筛选"),
    stage: Optional[str] = Query(None, description="按阶段筛选"),
    min_score: Optional[int] = Query(None, ge=0, le=100, description="最低分数"),
):
    """导出项目列表."""
    logger.info(
        "api.export.projects",
        format=format,
        label=label,
        sector=sector,
        min_score=min_score,
    )

    try:
        # 查询项目（不分页，获取所有）
        repo = ProjectRepository()
        db_projects, total = repo.list_projects(
            page=1,
            page_size=10000,  # 大数字获取所有
            label=label,
            sector=sector,
            stage=stage,
            min_score=min_score,
            sort_by="score",
            sort_order="desc",
        )

        if not db_projects:
            raise HTTPException(
                status_code=404,
                detail="没有找到符合条件的项目"
            )

        # 转换为导出格式
        projects = [
            {
                "id": p["id"],
                "name": p["name"],
                "url": p["url"],
                "sector": p["sector"],
                "stage": p["stage"],
                "score": p["score"],
                "label": p["label"],
                "confidence": p["confidence"],
                "created_at": p["created_at"],
                "updated_at": p["updated_at"],
            }
            for p in db_projects
        ]

        # 生成文件
        if format == "excel":
            file_content = export_projects_to_excel(projects)
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            filename = f"projects_{label or 'all'}.xlsx"
        else:  # csv
            file_content = export_projects_to_csv(projects)
            media_type = "text/csv"
            filename = f"projects_{label or 'all'}.csv"

        logger.info(
            "api.export.projects.success",
            format=format,
            project_count=len(projects),
        )

        return Response(
            content=file_content if isinstance(file_content, bytes) else file_content.encode('utf-8'),
            media_type=media_type,
            headers={
                "Content-Disposition": f"attachment; filename={filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.export.projects.failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"导出失败: {str(e)}"
        )


@router.get(
    "/export/project/{project_id}",
    summary="导出单个项目详情",
    description="导出单个项目的完整详情到 Excel（包含所有分析结果）",
)
async def export_project_detail(
    project_id: str = Path(..., description="项目 ID"),
):
    """导出单个项目详情."""
    logger.info(
        "api.export.project",
        project_id=project_id,
    )

    try:
        # 查询项目
        repo = ProjectRepository()
        project = repo.get_by_id(project_id)

        if not project:
            raise HTTPException(
                status_code=404,
                detail=f"项目 {project_id} 不存在"
            )

        # 解析 JSON 字段
        import json
        project_detail = {
            "id": project["id"],
            "name": project["name"],
            "url": project["url"],
            "sector": project["sector"],
            "stage": project["stage"],
            "score": project["score"],
            "label": project["label"],
            "confidence": project["confidence"],
            "reason": json.loads(project["reason"]) if project.get("reason") else None,
            "narrative": json.loads(project["narrative_json"]) if project.get("narrative_json") else None,
            "team": json.loads(project["team_json"]) if project.get("team_json") else None,
            "risk": json.loads(project["risk_json"]) if project.get("risk_json") else None,
            "tokenomics": json.loads(project["tokenomics_json"]) if project.get("tokenomics_json") else None,
            "created_at": project["created_at"],
            "updated_at": project["updated_at"],
        }

        # 生成 Excel
        file_content = export_project_detail_to_excel(project_detail)
        filename = f"{project['name']}_详情.xlsx"

        logger.info(
            "api.export.project.success",
            project_id=project_id,
        )

        return Response(
            content=file_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename*=UTF-8''{filename}"
            }
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.export.project.failed",
            project_id=project_id,
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"导出失败: {str(e)}"
        )


@router.get(
    "/export/template",
    summary="下载导入模板",
    description="下载 Excel 导入模板，包含示例数据和必填字段说明",
)
async def download_import_template():
    """下载导入模板."""
    logger.info("api.export.template")

    try:
        file_content = create_import_template_excel()

        return Response(
            content=file_content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": "attachment; filename=import_template.xlsx"
            }
        )

    except Exception as e:
        logger.error(
            "api.export.template.failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"模板生成失败: {str(e)}"
        )


@router.post(
    "/import/projects",
    response_model=RunResponse,
    summary="批量导入项目并评分",
    description=(
        "上传 Excel 或 CSV 文件批量导入项目，并自动运行评分 Pipeline。\n\n"
        "## 支持格式\n\n"
        "- Excel (.xlsx)\n"
        "- CSV (.csv)\n\n"
        "## 必填字段\n\n"
        "- 项目名称 (name)\n\n"
        "## 可选字段\n\n"
        "- URL\n"
        "- 赛道 (sector)\n"
        "- 阶段 (stage)\n"
        "- 有测试网 (has_testnet)\n"
        "- 有积分计划 (has_points_program)\n"
        "- 未发币 (no_token_yet)\n"
        "- 近期融资 (recent_funding)\n\n"
        "## 限制\n\n"
        "- 最多导入 100 个项目\n"
        "- 文件大小限制 10MB"
    ),
)
async def import_projects(
    file: UploadFile = File(..., description="Excel 或 CSV 文件"),
    enable_llm: bool = Query(False, description="是否启用 LLM 增强"),
):
    """批量导入项目并评分."""
    logger.info(
        "api.import.projects",
        filename=file.filename,
        content_type=file.content_type,
    )

    try:
        # 读取文件内容
        content = await file.read()

        # 根据文件类型导入
        if file.filename.endswith('.xlsx') or file.content_type == 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet':
            projects_data = import_projects_from_excel(content)
        elif file.filename.endswith('.csv') or file.content_type == 'text/csv':
            projects_data = import_projects_from_csv(content.decode('utf-8'))
        else:
            raise HTTPException(
                status_code=400,
                detail="不支持的文件格式，请上传 .xlsx 或 .csv 文件"
            )

        # 验证数据
        valid_projects, errors = validate_imported_projects(projects_data)

        if errors:
            logger.warning(
                "api.import.validation_errors",
                error_count=len(errors),
                errors=errors[:10],  # 只记录前10个错误
            )

        if not valid_projects:
            raise HTTPException(
                status_code=400,
                detail={
                    "message": "没有有效的项目数据",
                    "errors": errors
                }
            )

        # 限制数量
        if len(valid_projects) > 100:
            raise HTTPException(
                status_code=400,
                detail=f"导入项目数量过多（{len(valid_projects)}），最多100个"
            )

        # 转换为 RawProject
        raw_projects = []
        for i, p in enumerate(valid_projects):
            raw_project = RawProject(
                id=f"import-{i+1:03d}",  # 生成导入 ID
                name=p["name"],
                url=p.get("url"),
                sector=p.get("sector"),
                stage=p.get("stage"),
                has_testnet=p.get("has_testnet", False),
                has_points_program=p.get("has_points_program", False),
                no_token_yet=p.get("no_token_yet", False),
                recent_funding=p.get("recent_funding", False),
                source="import",
            )
            raw_projects.append(raw_project)

        # 运行评分 Pipeline
        logger.info(
            "api.import.running_pipeline",
            project_count=len(raw_projects),
        )

        response = await run_orchestrator(
            projects=raw_projects,
            run_id=f"import-{file.filename}",
            enable_llm=enable_llm,
            save_to_db=True,
        )

        logger.info(
            "api.import.success",
            project_count=len(raw_projects),
            validation_errors=len(errors),
        )

        # 添加验证错误到响应
        if errors:
            response.validation_errors = errors

        return response

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "api.import.failed",
            error=str(e),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"导入失败: {str(e)}"
        )
