"""Script Forge Router (自动化交互脚本工坊路由).

POST /api/v1/scripts/generate
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.script_forge import generate_interaction_scripts

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/scripts", tags=["scripts"])


class ScriptRequest(BaseModel):
    project_name: str = Field(..., min_length=1, description="项目名称")
    task_type: str = Field("contract_mint", description="任务类型")
    # 必填：脚本会真实向该合约发交易，绝不内置占位地址（审计 P1）
    contract_address: str = Field(
        ..., pattern=r"^0x[0-9a-fA-F]{40}$", description="目标交互合约地址 (0x 开头 40 位十六进制，必填)"
    )
    rpc_url: str = Field(..., min_length=8, description="目标网络 RPC 节点地址 (必填)")
    jitter_min: int = Field(15, ge=1, le=300, description="防女巫随机延迟下限 (秒)")
    jitter_max: int = Field(60, ge=5, le=1800, description="防女巫随机延迟上限 (秒)")


@router.post("/generate", summary="一键生成多语言防女巫交互代码模版")
def generate_code(req: ScriptRequest) -> dict[str, Any]:
    """生成 Foundry Cast / Web3.py / Viem 交互脚本."""
    return generate_interaction_scripts(
        project_name=req.project_name,
        task_type=req.task_type,
        contract_address=req.contract_address,
        rpc_url=req.rpc_url,
        jitter_min=req.jitter_min,
        jitter_max=req.jitter_max,
    )
