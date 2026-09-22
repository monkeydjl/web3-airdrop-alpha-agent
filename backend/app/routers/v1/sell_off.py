"""Sell-Off Strategy Simulator API Router (空投领取代币出局与止盈模拟器路由).

POST /api/v1/sell-off/simulate
"""

from typing import Any, Literal
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.sell_off_simulator import simulate_sell_off_strategies

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/sell-off", tags=["sell-off"])


class SellOffSimulationRequest(BaseModel):
    token_amount: float = Field(..., gt=0, description="领取的空投代币数量")
    initial_price_usd: float = Field(..., gt=0, description="开盘/初始单价预估 (USD)")
    sector: str = Field("layer2", description="赛道类别 (layer2, infrastructure, defi, ai, other)")
    persona: Literal["conservative", "balanced", "aggressive", "farmer_whale"] = Field(
        "balanced", description="猎人投资风格画像"
    )


@router.post("/simulate", summary="模拟空投领取代币的 4 种止盈出局策略与期望回报")
def simulate_exit_strategy(req: SellOffSimulationRequest) -> dict[str, Any]:
    """根据领取代币数量、初始价值、赛道特征与风险画像，模拟 4 种不同止盈策略的回报与裁决分析."""
    return simulate_sell_off_strategies(
        token_amount=req.token_amount,
        initial_price_usd=req.initial_price_usd,
        sector=req.sector,
        persona=req.persona,
    )
