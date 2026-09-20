"""AI project brief endpoint — natural language interpretation.

带 meta 缓存（2026-09-06）：

- **GET 只读**：返回新鲜缓存或空态，**永不触发生成** —— 此前 GET 与 POST
  同义（都重新生成），把「进详情页看看」变成了「烧一次 LLM 预算」。
- **POST 生成**：`{"force": bool}`。force=false 时有新鲜缓存直接返回；
  无缓存或已过期（项目被重评/改融资等行更新推高 updated_at）才生成并
  写缓存。force=true 无视缓存强制重新生成。

异常原文只进日志、不进响应体：generate_project_brief 会走 LLM（httpx，
URL 可能带 ?api_key=...）或 DB 路径（异常可能带连接串），回显给调用方会
泄露密钥/DSN。与 run.py、opportunity.py、ai_chat.py 的策略保持一致。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from app.config import settings
from app.repository import ProjectRepository
from app.services.ai_brief import (
    generate_project_brief,
    get_cached_brief,
    store_brief_cache,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["ai"])

# 响应里透传的简报字段（缓存 payload 与新生成结果同构，走同一份白名单）。
_BRIEF_FIELDS = (
    "mode",
    "degraded_reason",
    "headline",
    "summary",
    "bullets",
    "paragraphs",
    "display_text",
    "label",
    "label_zh",
    "score",
    "confidence",
    "generated_at",
)


class AiBriefRequest(BaseModel):
    """POST 请求体；force=true 无视新鲜缓存强制重新生成。"""

    force: bool = False


def _payload(project: dict[str, Any], brief: dict[str, Any], *, cached: bool, stale: bool) -> dict[str, Any]:
    data: dict[str, Any] = {
        "project_id": project.get("id"),
        "project_name": project.get("name"),
        "llm_available": settings.is_llm_enabled,
        "cached": cached,
        "stale": stale,
    }
    data.update({k: brief.get(k) for k in _BRIEF_FIELDS})
    return data


def _get_project_or_404(project_id: str) -> dict[str, Any]:
    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )
    return dict(project)


@router.post("/projects/{project_id}/ai-brief")
async def project_ai_brief(
    req: AiBriefRequest | None = None,
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """生成（或读缓存）项目的自然语言简报。

    Uses rule-based synthesis always; upgrades to LLM when OPENAI_API_KEY is set.
    """
    project = _get_project_or_404(project_id)

    force = bool(req.force) if req is not None else False
    stale = False
    if not force:
        cached_payload, stale = get_cached_brief(project)
        if cached_payload:
            return {"ok": True, "data": _payload(project, cached_payload, cached=True, stale=False)}

    try:
        brief = await generate_project_brief(project)
    except Exception as e:
        logger.error("ai_brief.failed", project_id=project_id, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "BRIEF_FAILED", "message": "Failed to generate project brief"},
        ) from e

    store_brief_cache(project_id, brief)
    return {"ok": True, "data": _payload(project, brief, cached=False, stale=stale)}


@router.get("/projects/{project_id}/ai-brief")
def project_ai_brief_get(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """只读缓存。有新鲜缓存返回完整简报（cached=true）；没有或已过期
    返回空态（cached=false + stale 标记），**不触发生成**。

    刻意是同步 def 而不是 async def：整条路径只有内存/DB 同步调用，
    async 无 await 会在事件循环上执行阻塞工作（
    test_no_async_route_handler_is_purely_synchronous 的门禁判据）——
    FastAPI 会把同步 def 放进线程池。
    """
    project = _get_project_or_404(project_id)
    payload, stale = get_cached_brief(project)
    if payload:
        return {"ok": True, "data": _payload(project, payload, cached=True, stale=False)}
    return {"ok": True, "data": _payload(project, {}, cached=False, stale=stale)}
