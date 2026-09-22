"""Script Forge Router (自动化交互脚本工坊路由).

POST /api/v1/scripts/generate
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.script_forge import generate_interaction_scripts

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/scripts", tags=["scripts"])


class ScriptRequest(BaseModel):
    project_name: str = Field("Story Protocol", description="项目名称")
    task_type: str = Field("contract_mint", description="任务类型")
    contract_address: str = Field("0x7777777254eeb25477b68fb85ed929f73a960582", description="交互合约地址")
    rpc_url: str = Field("https://odyssey.storyrpc.io", description="RPC 节点地址")
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
