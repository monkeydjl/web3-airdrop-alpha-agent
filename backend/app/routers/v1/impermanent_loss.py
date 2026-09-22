"""Impermanent Loss & Lending Liquidation Sentinel API Router.

POST /api/v1/il-sentinel/calculate-il
POST /api/v1/il-sentinel/check-lending-health
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.impermanent_loss_sentinel import (
    calculate_amm_impermanent_loss,
    check_lending_health_factor,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/il-sentinel", tags=["il-sentinel"])


class IlCalculateRequest(BaseModel):
    initial_deposit_usd: float = Field(default=5000.0, ge=1.0, description="初始存入 LP 资金 (USD)")
    price_change_pct: float = Field(default=30.0, description="资产价格相对变化百分比 (%)")
    is_concentrated_v3: bool = Field(default=True, description="是否为 Uni V3 集中流动性")
    price_lower_bound_ratio: float = Field(default=0.8, ge=0.01, description="做市区间下限比率")
    price_upper_bound_ratio: float = Field(default=1.2, ge=0.02, description="做市区间上限比率")
    fee_apy_pct: float = Field(default=24.0, ge=0.0, description="预期年化手续费率 (%)")
    holding_days: int = Field(default=30, ge=1, le=730, description="持有做市天数")


class LendingHealthRequest(BaseModel):
    collateral_asset: str = Field(default="ETH", description="抵押物代币符号")
    collateral_amount: float = Field(default=5.0, ge=0.001, description="抵押代币数量")
    collateral_price_usd: float = Field(default=3200.0, ge=1.0, description="当前抵押物单价 (USD)")
    liquidation_threshold: float = Field(default=0.825, ge=0.1, le=1.0, description="协议清算阈值比率")
    borrowed_usd: float = Field(default=10000.0, ge=1.0, description="已借出负债总额 (USD)")


@router.post("/calculate-il", summary="测算 AMM 流动性池的无常损失与手续费净收益")
def calculate_il(req: IlCalculateRequest) -> dict[str, Any]:
    result = calculate_amm_impermanent_loss(
        initial_deposit_usd=req.initial_deposit_usd,
        price_change_pct=req.price_change_pct,
        is_concentrated_v3=req.is_concentrated_v3,
        price_lower_bound_ratio=req.price_lower_bound_ratio,
        price_upper_bound_ratio=req.price_upper_bound_ratio,
        fee_apy_pct=req.fee_apy_pct,
        holding_days=req.holding_days,
    )
    return {"ok": True, "data": result}


@router.post("/check-lending-health", summary="监控借贷仓位健康因子与以太坊清算极限价格")
def check_lending_health(req: LendingHealthRequest) -> dict[str, Any]:
    result = check_lending_health_factor(
        collateral_asset=req.collateral_asset,
        collateral_amount=req.collateral_amount,
        collateral_price_usd=req.collateral_price_usd,
        liquidation_threshold=req.liquidation_threshold,
        borrowed_usd=req.borrowed_usd,
    )
    return {"ok": True, "data": result}
