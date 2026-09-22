"""Airdrop PnL Router (空投收益账本与历史战绩复盘路由).

GET /api/v1/pnl/summary
POST /api/v1/pnl/records
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.airdrop_pnl import (
    add_harvest_record,
    get_pnl_summary,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/pnl", tags=["pnl"])


class HarvestRecordRequest(BaseModel):
    project_name: str = Field(..., description="空投项目名称")
    token_symbol: str = Field(..., description="代币符号，如 $ARB")
    amount_claimed: float = Field(..., gt=0, description="领取代币数量")
    current_price_usd: float = Field(..., ge=0, description="当前代币价格 (USD)")
    ath_price_usd: float = Field(..., ge=0, description="历史最高价格 (USD)")
    gas_spent_usd: float = Field(0.0, ge=0, description="投入的累计 Gas 成本 (USD)")
    notes: str = Field("", description="复盘备注说明")


@router.get("/summary", summary="获取空投真实收益汇总、RoI 与猎人荣誉段位")
def get_summary() -> dict[str, Any]:
    """汇总已领取的空投价值、净利润与战绩段位."""
    return get_pnl_summary()


@router.post("/records", summary="记录一笔新到账的空投代币")
def record_harvest(req: HarvestRecordRequest) -> dict[str, Any]:
    """录入新空投资产."""
    return add_harvest_record(req.model_dump())
