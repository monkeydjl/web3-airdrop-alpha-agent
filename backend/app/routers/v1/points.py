"""Airdrop Epoch Points Estimator API Router (空投积分估值与快照倍数推演路由).

GET /api/v1/points/supported-protocols
POST /api/v1/points/estimate
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.points_epoch_estimator import (
    get_supported_protocols,
    estimate_points_airdrop,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/points", tags=["points"])


class PointsEstimateRequest(BaseModel):
    protocol_id: str = Field(..., description="协议标识 (scroll_marks, linea_voyage, hyperliquid_points, symbiotic_points, karak_xp)")
    user_points: float = Field(..., ge=0.0, description="用户当前持有的积分/XP数量")
    capital_invested_usd: float = Field(0.0, ge=0.0, description="投入本金/流动性估值 (USD)")
    days_active: int = Field(30, ge=1, description="活跃天数")


@router.get("/supported-protocols", summary="获取所有支持积分与快照估值的协议模型")
def list_protocols() -> dict[str, Any]:
    """返回支持的积分制协议列表、代币符号与总量参数."""
    return {"ok": True, "data": get_supported_protocols()}


@router.post("/estimate", summary="推演当前积分的全网排位、代币折算估值与加权冲刺方案")
def estimate_airdrop(req: PointsEstimateRequest) -> dict[str, Any]:
    """根据持有的积分数量、本金与协议模型，推演预估空投代币数、美元估值与冲刺建议."""
    return estimate_points_airdrop(
        protocol_id=req.protocol_id,
        user_points=req.user_points,
        capital_invested_usd=req.capital_invested_usd,
        days_active=req.days_active,
    )
