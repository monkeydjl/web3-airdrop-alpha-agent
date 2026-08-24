"""AI project brief endpoint — natural language interpretation."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, HTTPException, Path

from app.config import settings
from app.repository import ProjectRepository
from app.services.ai_brief import generate_project_brief

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ai"])


@router.post("/projects/{project_id}/ai-brief")
async def project_ai_brief(
    project_id: str = Path(..., description="项目 ID"),
):
    """Generate a natural-language brief for a scored project.

    Uses rule-based synthesis always; upgrades to LLM when OPENAI_API_KEY is set.
    """
    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )

    try:
        brief = await generate_project_brief(dict(project))
    except Exception as e:
        # 异常原文只进日志、不进响应体：generate_project_brief 会走 LLM(httpx，
        # URL 可能带 ?api_key=...) 或 DB 路径(异常可能带连接串)，回显给调用方会
        # 泄露密钥/DSN。与 run.py、opportunity.py 的策略保持一致。
        logger.error("ai_brief.failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "BRIEF_FAILED", "message": "Failed to generate project brief"},
        ) from e

    return {
        "ok": True,
        "data": {
            "project_id": project_id,
            "project_name": project.get("name"),
            "mode": brief.get("mode"),
            "llm_available": settings.is_llm_enabled,
            # 回退到规则引擎的原因。`llm_disabled`（没配密钥）/
            # `budget_exceeded`（日预算用完）/ `ledger_unavailable`（账本故障）/
            # `llm_error`（接口挂了）。`mode == "llm"` 时为 null。
            #
            # 只有 mode 而没有原因时，前端只能对所有降级说同一句话 ——
            # 而"没配密钥"和"预算用完了"的处置动作完全不同，
            # 说错会把人引向错误的排查方向。
            "degraded_reason": brief.get("degraded_reason"),
            "headline": brief.get("headline"),
            "summary": brief.get("summary"),
            "bullets": brief.get("bullets") or [],
            "paragraphs": brief.get("paragraphs") or [],
            "display_text": brief.get("display_text") or "",
            "label": brief.get("label"),
            "label_zh": brief.get("label_zh"),
            "score": brief.get("score"),
            "confidence": brief.get("confidence"),
        },
    }


@router.get("/projects/{project_id}/ai-brief")
async def project_ai_brief_get(
    project_id: str = Path(..., description="项目 ID"),
):
    """GET alias for convenience (same as POST)."""
    return await project_ai_brief(project_id)
