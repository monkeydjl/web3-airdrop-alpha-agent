"""Multi-Operator Team Studio API Router.

GET  /api/v1/team-studio/dashboard
POST /api/v1/team-studio/assign-task
POST /api/v1/team-studio/operator
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.team_studio_manager import (
    assign_task_to_operator,
    get_team_studio_dashboard,
    register_or_update_operator,
)

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
    assigned_projects: list[str] = Field(default_factory=lambda: ["Scroll"], description="负责的项目列表")


@router.get("/dashboard", summary="获取工作室团队协同全局指标与操作员表现")
def get_studio_dashboard() -> dict[str, Any]:
    data = get_team_studio_dashboard()
    return {"ok": True, "data": data}


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
