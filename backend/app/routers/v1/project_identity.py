"""项目身份别名 API（/api/v1/project-identity）。

与 `routers/v1/identity.py`（钱包身份 / 护照）无关：这里管理的是**项目**身份
（`dedup_key → project_id`）的别名映射，用于项目改名、赛道写法差异、跨源命名
差异时仍解析到同一个稳定 project_id。

端点：
- GET    /api/v1/project-identity/aliases
- POST   /api/v1/project-identity/aliases
- DELETE /api/v1/project-identity/aliases/{alias_id}
- POST   /api/v1/project-identity/resolve
- POST   /api/v1/project-identity/aliases/backfill

写操作在 `app/auth.py` 的 ADMIN_ONLY_METHOD_RULES 里按方法收紧为管理员专属
（别名是全局身份数据，改错会波及所有用户）。
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.identity import (
    ALIAS_SOURCE_BACKFILL,
    ALIAS_SOURCE_MANUAL,
    ProjectIdentityResolver,
    backfill_project_aliases,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/project-identity", tags=["project-identity"])


class AliasCreateRequest(BaseModel):
    dedup_key: str = Field(
        ...,
        min_length=3,
        max_length=256,
        description="别名键，格式 name::Sector；name::* 为名称级别名（仅手工配置）",
    )
    project_id: str = Field(..., min_length=8, max_length=128, description="别名指向的稳定项目 ID")
    confidence: float | None = Field(None, ge=0.0, le=1.0, description="可信度，省略按来源取默认值")
    notes: str | None = Field(None, max_length=500, description="人工备注")


class ResolveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="项目原始名称")
    sector: str | None = Field(None, max_length=120, description="项目赛道（可空）")


class BackfillRequest(BaseModel):
    apply: bool = Field(False, description="false = dry-run 只出报告；true 才写库")
    limit: int | None = Field(None, ge=1, le=100000, description="最多扫描多少条 projects 行")


@router.get("/aliases", summary="列出项目身份别名（按 project_id / source 过滤）")
def list_aliases(
    project_id: str | None = Query(None, description="只看某个项目下的别名"),
    source: str | None = Query(None, description="manual / backfill / auto"),
    limit: int = Query(500, ge=1, le=5000),
) -> dict[str, Any]:
    rows = ProjectIdentityResolver().list_aliases(project_id=project_id, source=source, limit=limit)
    return {"ok": True, "data": {"aliases": rows, "total": len(rows)}, "error": None}


@router.post("/aliases", summary="新增/覆盖一条手工别名（优先级最高）")
def create_alias(req: AliasCreateRequest) -> dict[str, Any]:
    resolver = ProjectIdentityResolver()
    try:
        result = resolver.upsert_alias(
            req.dedup_key,
            req.project_id,
            source=ALIAS_SOURCE_MANUAL,
            confidence=req.confidence,
            notes=req.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("applied"):
        raise HTTPException(status_code=409, detail=f"别名写入被拒绝：{result.get('reason')}")
    return {"ok": True, "data": result, "error": None}


@router.delete("/aliases/{alias_id}", summary="删除一条别名（不会改动任何项目数据）")
def delete_alias(alias_id: int) -> dict[str, Any]:
    deleted = ProjectIdentityResolver().delete_alias(alias_id)
    if not deleted:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "alias not found"})
    return {"ok": True, "data": {"alias_id": alias_id, "deleted": True}, "error": None}


@router.post("/resolve", summary="调试：查看某个名称/赛道最终解析到哪个 project_id")
def resolve_identity(req: ResolveRequest) -> dict[str, Any]:
    identity = ProjectIdentityResolver().resolve(req.name, req.sector)
    return {
        "ok": True,
        "data": {
            "project_id": identity.project_id,
            "name_key": identity.name_key,
            "sector_key": identity.sector_key,
            "alias_key": identity.alias_key,
            "source": identity.source,
            "confidence": identity.confidence,
            "matched": identity.matched,
            "is_legacy": identity.is_legacy,
        },
        "error": None,
    }


@router.post("/aliases/backfill", summary="把既有 projects 行的 ID 钉成 backfill 别名（默认 dry-run）")
def backfill_aliases(req: BackfillRequest) -> dict[str, Any]:
    report = backfill_project_aliases(apply=req.apply, limit=req.limit)
    data = report.to_dict()
    data["source"] = ALIAS_SOURCE_BACKFILL
    return {"ok": True, "data": data, "error": None}
