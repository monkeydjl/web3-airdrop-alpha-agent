"""Bridge Optimizer Router (跨链路由与低磨损资金规划路由).

GET /api/v1/bridge/supported-chains
POST /api/v1/bridge/route
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.bridge_optimizer import (
    calculate_bridge_routes,
    get_supported_bridge_chains,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/bridge", tags=["bridge"])


class BridgeRouteRequest(BaseModel):
    source_chain: str = Field("arbitrum", description="源链代号 (如 arbitrum, base, ethereum)")
    target_chain: str = Field("base", description="目标链代号 (如 base, optimism, scroll)")
    token: str = Field("ETH", description="代币符号 (ETH 或 USDC)")
    amount: float = Field(0.5, gt=0, description="转移代币数量")


@router.get("/supported-chains", summary="获取支持的跨链网络与基础 Gas 特征")
def list_chains() -> dict[str, Any]:
    """返回所有支持比对的链及其平均 Gas 成本."""
    return {"ok": True, "chains": get_supported_bridge_chains()}


@router.post("/route", summary="智能计算全网跨链最优费率与防女巫资金归集路线")
def compute_route(req: BridgeRouteRequest) -> dict[str, Any]:
    """比对 Across, Stargate, Hop, Orbiter 与官方桥，推荐极低磨损与极速方案."""
    result = calculate_bridge_routes(
        source_chain=req.source_chain,
        target_chain=req.target_chain,
        token=req.token,
        amount=req.amount,
    )
    return {"ok": True, "data": result}
