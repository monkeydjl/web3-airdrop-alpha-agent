"""Cross-Chain Bridge Liquidity & Depeg Radar API Router.

GET  /api/v1/bridge-liquidity/overview
POST /api/v1/bridge-liquidity/simulate-route
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.bridge_liquidity_radar import get_bridge_liquidity_overview, simulate_bridge_route

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/bridge-liquidity", tags=["bridge-liquidity"])


class BridgeRouteSimulateRequest(BaseModel):
    from_chain: str = Field(default="Ethereum", description="源链名称")
    to_chain: str = Field(default="Arbitrum", description="目标链名称")
    asset: str = Field(default="USDC", description="跨链资产币种")
    amount_usd: float = Field(default=10000.0, ge=1.0, description="跨链资金金额 (USD)")
    bridge_preference: str = Field(default="across", description="跨链桥偏好")


@router.get("/overview", summary="获取全网跨链池流动性健康与代币脱锚大盘")
def get_liquidity_overview() -> dict[str, Any]:
    data = get_bridge_liquidity_overview()
    return {"ok": True, "data": data}


@router.post("/simulate-route", summary="精确推演指定路径的跨链滑点与枯竭风险")
def simulate_route(req: BridgeRouteSimulateRequest) -> dict[str, Any]:
    result = simulate_bridge_route(
        from_chain=req.from_chain,
        to_chain=req.to_chain,
        asset=req.asset,
        amount_usd=req.amount_usd,
        bridge_preference=req.bridge_preference,
    )
    return {"ok": True, "data": result}
