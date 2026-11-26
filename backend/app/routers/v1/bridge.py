"""Bridge Optimizer Router (跨链路由与低磨损资金规划路由).

GET /api/v1/bridge/supported-chains
POST /api/v1/bridge/route
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.bridge_optimizer import (
    calculate_bridge_routes_live,
    get_supported_bridge_chains,
)
from app.utils.data_quality import mark_real, mark_simulated

_BRIDGE_NOTE = "LI.FI 实时报价当前不可用或处于离线测试模式，已回退静态估算参数，报价仅供对比。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/bridge", tags=["bridge"])


class BridgeRouteRequest(BaseModel):
    source_chain: str = Field("arbitrum", description="源链代号 (如 arbitrum, base, ethereum)")
    target_chain: str = Field("base", description="目标链代号 (如 base, optimism, scroll)")
    token: str = Field("ETH", description="代币符号 (ETH 或 USDC)")
    amount: float = Field(0.5, gt=0, description="转移代币数量")


@router.get("/supported-chains", summary="获取支持的跨链网络与基础 Gas 特征")
def list_chains() -> dict[str, Any]:
    """返回所有支持比对的链及其平均 Gas 成本（静态演示参数）."""
    return mark_simulated({"ok": True, "chains": get_supported_bridge_chains()}, note=_BRIDGE_NOTE)


@router.post("/route", summary="智能计算全网跨链最优费率与防女巫资金归集路线")
async def compute_route(req: BridgeRouteRequest) -> dict[str, Any]:
    """优先调用 LI.FI 公开聚合报价，离线/失败时自动回退本地估算并诚实标为 simulated."""
    result, is_live = await calculate_bridge_routes_live(
        source_chain=req.source_chain,
        target_chain=req.target_chain,
        asset=req.token,
        amount=req.amount,
    )
    if is_live:
        return mark_real({"ok": True, "data": result}, note="首推路线来自 LI.FI 公开 API 实时跨链报价")
    return mark_simulated({"ok": True, "data": result}, note=_BRIDGE_NOTE)
