"""Airdrop Action Playbook Studio API Router.

GET  /api/v1/playbook/templates
POST /api/v1/playbook/validate-and-generate
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.playbook_orchestrator import (
    list_playbook_templates,
    validate_and_generate_playbook_script,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/playbook", tags=["playbook"])


class PlaybookGenerateRequest(BaseModel):
    playbook_id: str | None = Field(default=None, description="预设 Playbook ID")
    custom_title: str | None = Field(default=None, description="自定义流水线标题")
    custom_steps: list[dict[str, Any]] | None = Field(default=None, description="自定义步骤列表")
    jitter_min: int = Field(default=30, ge=1, le=3600, description="防女巫最小延迟 (秒)")
    jitter_max: int = Field(default=90, ge=1, le=3600, description="防女巫最大延迟 (秒)")
    language: str = Field(default="python", description="输出脚本语言")


@router.get("/templates", summary="获取所有官方推荐与精选 Playbook 任务流模板")
def get_playbook_templates() -> dict[str, Any]:
    templates = list_playbook_templates()
    return {"ok": True, "data": {"templates": templates, "total": len(templates)}}


@router.post("/validate-and-generate", summary="校验步骤并生成带防女巫延迟的自动化脚本")
def generate_playbook_script(req: PlaybookGenerateRequest) -> dict[str, Any]:
    result = validate_and_generate_playbook_script(
        playbook_id=req.playbook_id,
        custom_title=req.custom_title,
        custom_steps=req.custom_steps,
        jitter_range_seconds=(req.jitter_min, req.jitter_max),
        language=req.language,
    )
    return {"ok": True, "data": result}
