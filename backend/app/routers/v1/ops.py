"""Operations Maintenance Router (全库数据维护与审计运维端点).

Provides admin-only endpoints for database-wide tasks:
- POST /api/v1/ops/sync-funding: Sync DefiLlama protocol funding data across projects.
- POST /api/v1/ops/audit-viability: Batch audit project viability and runway health.
- GET /api/v1/ops/audit-logs: Query redacted admin mutation security audit logs.

Protected by `ADMIN_ONLY_PREFIXES` in `app.auth`.
"""

from __future__ import annotations

import asyncio
from typing import Any

import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from app.services.audit_log import list_admin_audit_logs
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


class AuditLogEntry(BaseModel):
    id: int = Field(..., description="审计记录自增 ID")
    action: str = Field(..., description="管理员写操作标识（例如 POST /api/v1/ops/audit-viability）")
    user: str = Field(..., description="执行操作的管理员或本机主体标识")
    detail: str | None = Field(default=None, description="已脱敏的上下文详情 JSON 字符串")
    ip: str | None = Field(default=None, description="请求来源客户端 IP")
    created_at: str | None = Field(default=None, description="审计记录写入时间")


class AuditLogListData(BaseModel):
    items: list[AuditLogEntry] = Field(default_factory=list, description="按时间倒序排列的审计日志列表")
    total: int = Field(..., description="本次返回的记录条数")


class AuditLogListResponse(BaseModel):
    ok: bool = Field(True, description="查询是否成功")
    data: AuditLogListData = Field(..., description="审计日志查询结果")


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


@router.get(
    "/audit-logs",
    response_model=AuditLogListResponse,
    summary="查询管理员写操作安全审计日志",
    description="按操作类型或管理员标识倒序查询 `audit_logs` 表记录（所有写入均已完成密钥脱敏）。",
)
async def ops_list_audit_logs(
    request: Request,
    action: str | None = Query(default=None, description="按动作精确过滤，例如 POST /api/v1/ops/audit-viability"),
    user: str | None = Query(default=None, description="按操作者标识精确过滤"),
    limit: int = Query(default=50, ge=1, le=500, description="返回记录数上限"),
) -> AuditLogListResponse:
    override_conn = getattr(request.app.state, "db_override", None)
    if override_conn is not None:
        rows = list_admin_audit_logs(action=action, user=user, limit=limit, conn=override_conn)
    else:
        rows = await asyncio.to_thread(
            list_admin_audit_logs,
            action=action,
            user=user,
            limit=limit,
        )
    entries = [AuditLogEntry.model_validate(row) for row in rows]
    return AuditLogListResponse(ok=True, data=AuditLogListData(items=entries, total=len(entries)))
