"""Multi-Operator Team Studio API Router.

GET  /api/v1/team-studio/dashboard
POST /api/v1/team-studio/assign-task
POST /api/v1/team-studio/operator

诚实口径：看板不再内置虚构操作员，从空态开始；团队数据已持久化到 SQLite
（重启保留），但今日完成 tx / Gas 等运行指标无真实数据源，整体仍打
``simulated`` 标记。
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.team_studio_manager import (
    assign_task_to_operator,
    get_team_studio_dashboard,
    register_or_update_operator,
)
from app.utils.data_quality import mark_simulated

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/team-studio", tags=["team-studio"])


class AssignTaskRequest(BaseModel):
    title: str = Field(..., min_length=2, max_length=100, description="任务标题")
    project: str = Field(..., min_length=2, max_length=50, description="所属协议/项目")
    operator_id: str = Field(..., description="指派的操作员 ID")
    target_wallet_count: int = Field(default=10, ge=1, le=500, description="目标执行钱包数量")
    priority: str = Field(default="medium", description="优先级: high / medium / low")
    deadline: str = Field(default="今日 24:00", description="截止时效说明")


class OperatorRequest(BaseModel):
    operator_id: str = Field(..., min_length=2, max_length=50, description="操作员唯一标识")
    name: str = Field(..., min_length=2, max_length=50, description="操作员姓名或昵称")
    role: str = Field(default="Operator", description="岗位角色")
    assigned_wallets: int = Field(default=10, ge=1, le=1000, description="名下分配钱包数量")
    assigned_projects: list[str] = Field(default_factory=list, description="负责的项目列表")


@router.get("/dashboard", summary="获取工作室团队看板（空态诚实，无预置演示数据）")
def get_studio_dashboard() -> dict[str, Any]:
    data = get_team_studio_dashboard()
    # data_quality 统一打在响应体顶层（与 data_quality 契约及前端读取口径一致）。
    # 数据已落库，但运行指标（完成 tx / Gas）无真实数据源，诚实标记保留。
    resp = {"ok": True, "data": data}
    return mark_simulated(
        resp,
        note="团队与任务数据已持久化到 SQLite（重启保留）；今日完成 tx / Gas 等运行指标无真实数据源。",
    )


@router.post("/assign-task", summary="为指定操作员派发新任务")
def assign_task(req: AssignTaskRequest) -> dict[str, Any]:
    res = assign_task_to_operator(
        title=req.title,
        project=req.project,
        operator_id=req.operator_id,
        target_wallet_count=req.target_wallet_count,
        priority=req.priority,
        deadline=req.deadline,
    )
    if not res.get("success"):
        return {"ok": False, "error": {"code": "OPERATOR_NOT_FOUND", "message": res.get("error", "操作员不存在")}}
    return {"ok": True, "data": res}


@router.post("/operator", summary="新增或更新操作员信息")
def save_operator(req: OperatorRequest) -> dict[str, Any]:
    res = register_or_update_operator(
        operator_id=req.operator_id,
        name=req.name,
        role=req.role,
        assigned_wallets=req.assigned_wallets,
        assigned_projects=req.assigned_projects,
    )
    return {"ok": True, "data": res}
