"""HA & Leader Election Status Endpoints (W12-03, ADR-005).

Provides read-only cluster leadership and scheduler state endpoints for
multi-instance deployments, health checks, and ops monitoring.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.db import get_connection
from app.services.leader_election import LeaderElector

router = APIRouter(tags=["ha"])


class HAStatusData(BaseModel):
    """HA 选主与调度者状态数据。"""

    ha_enabled: bool = Field(..., description="是否启用了多实例 HA 选主")
    resource_id: str = Field(..., description="受控资源标识符")
    instance_id: str = Field(..., description="当前实例 ID")
    is_leader: bool = Field(..., description="当前实例是否为活动 Leader")
    current_leader: str | None = Field(default=None, description="集群当前持有租约的 Leader ID")
    lease_expires_at: str | None = Field(default=None, description="租约到期时间 (UTC)")
    acquired_at: str | None = Field(default=None, description="租约获取时间 (UTC)")
    version: int = Field(default=0, description="租约乐观锁版本号")
    lease_ttl_seconds: int = Field(..., description="租约有效时长（秒）")
    heartbeat_interval_seconds: int = Field(..., description="心跳续约间隔（秒）")
    status: str = Field(default="standalone", description="当前实例选主状态 (leader | follower | standalone)")


class HAStatusResponse(BaseModel):
    """HA 选主状态响应。"""

    ok: bool = True
    data: HAStatusData


@router.get(
    "/ha/status",
    response_model=HAStatusResponse,
    summary="获取集群选主与 HA 状态",
    description="查询当前实例的高可用选主状态、Leader 实例标识与租约有效期（公开只读）。",
)
def get_ha_status(request: Request) -> HAStatusResponse:
    """获取当前实例的 HA 选主与租约状态。"""
    elector = getattr(request.app.state, "leader_elector", None)
    if elector is not None and isinstance(elector, LeaderElector):
        status = elector.get_status()
    else:
        # Fallback to direct DB query if elector not initialized on app state
        temp_elector = LeaderElector(get_connection)
        status = temp_elector.get_status()

    return HAStatusResponse(ok=True, data=HAStatusData(**status))
