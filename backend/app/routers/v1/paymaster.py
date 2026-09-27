"""Paymaster Sponsor Radar API Router.

GET  /api/v1/paymaster/active-sponsorships
POST /api/v1/paymaster/simulate-gasless-tx
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.paymaster_sponsor_radar import (
    list_active_paymaster_sponsorships,
    simulate_gasless_tx,
)
from app.utils.data_quality import mark_simulated

_PAYMASTER_NOTE = "赞助活动与补贴池余量为静态演示数据（未接 ERC-4337 索引器），资格校验仅验证地址格式。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/paymaster", tags=["paymaster"])


class GaslessSimulateRequest(BaseModel):
    campaign_id: str = Field(default="base_daily_checkin", description="免 Gas 赞助活动 ID")
    user_address: str = Field(default="0x1111111111111111111111111111111111111111", description="待检测的钱包地址")


@router.get("/active-sponsorships", summary="获取全网当前活跃且资金池充沛的 Paymaster 免 Gas 活动")
def get_active_sponsorships(chain_id: int | None = None) -> dict[str, Any]:
    sponsorships = list_active_paymaster_sponsorships(chain_id)
    return mark_simulated(
        {"ok": True, "data": {"sponsorships": sponsorships, "total": len(sponsorships)}},
        note=_PAYMASTER_NOTE,
    )


@router.post("/simulate-gasless-tx", summary="模拟检测指定钱包在指定 Paymaster 下的赞助资格")
def simulate_gasless(req: GaslessSimulateRequest) -> dict[str, Any]:
    result = simulate_gasless_tx(campaign_id=req.campaign_id, user_address=req.user_address)
    return mark_simulated({"ok": True, "data": result}, note=_PAYMASTER_NOTE)
