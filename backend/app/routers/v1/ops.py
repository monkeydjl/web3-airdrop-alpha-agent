"""Operations Maintenance Router (全库数据维护与审计运维端点).

Provides admin-only endpoints for database-wide tasks:
- POST /api/v1/ops/sync-funding: Sync DefiLlama protocol funding data across projects.
- POST /api/v1/ops/audit-viability: Batch audit project viability and runway health.

Protected by `ADMIN_ONLY_PREFIXES` in `app.auth`.
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.ops_tasks import audit_database_viability, sync_database_defillama_raises

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/ops", tags=["ops"])


class OpsSyncFundingRequest(BaseModel):
    apply_changes: bool = Field(
        default=False,
        description="是否真实写入数据库。为 false 时仅进行 dry-run 匹配与预览。",
    )
    limit: int = Field(
        default=0,
        ge=0,
        description="限制扫描的项目数量，0 表示扫描全库。",
    )


class OpsAuditViabilityRequest(BaseModel):
    apply_changes: bool = Field(
        default=False,
        description="是否真实更新数据库与降级 FARM 项目。为 false 时仅输出审计报告。",
    )


class OpsTaskResponse(BaseModel):
    ok: bool = Field(True, description="任务是否成功执行")
    data: dict[str, Any] = Field(..., description="任务执行结果详情")


@router.post(
    "/sync-funding",
    response_model=OpsTaskResponse,
    summary="批量同步全库 DefiLlama 免费融资数据",
    description="扫描数据库中现有项目，匹配 DefiLlama 协议详情并抽取免费融资历史，可预览或持久化写入。",
)
async def ops_sync_funding(req: OpsSyncFundingRequest | None = None) -> OpsTaskResponse:
    request = req or OpsSyncFundingRequest()
    result = await sync_database_defillama_raises(
        apply_changes=request.apply_changes,
        limit=request.limit,
    )
    return OpsTaskResponse(ok=bool(result.get("ok", True)), data=result)


@router.post(
    "/audit-viability",
    response_model=OpsTaskResponse,
    summary="全库存活率与跑道健康度批量审计",
    description="全量执行存活率与跑道硬检验，识别纯积分盘、低融资与跑道耗尽项目，支持 dry-run 诊断或一键降级洗牌。",
)
def ops_audit_viability(req: OpsAuditViabilityRequest | None = None) -> OpsTaskResponse:
    request = req or OpsAuditViabilityRequest()
    result = audit_database_viability(apply_changes=request.apply_changes)
    return OpsTaskResponse(ok=bool(result.get("ok", True)), data=result)
