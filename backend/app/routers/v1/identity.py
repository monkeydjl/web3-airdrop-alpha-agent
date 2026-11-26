"""Web3 Identity & Passport Radar API Router.

POST /api/v1/identity/evaluate
GET  /api/v1/identity/stamping-guide
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.identity_passport_radar import evaluate_wallet_identity_live, get_stamping_guide
from app.utils.data_quality import mark_real, mark_simulated

_IDENTITY_LIVE_NOTE = (
    "链上/公开凭证（ENS、Linea POH、Snapshot 治理投票、合约多签）来自实时核验；"
    "链下 OAuth 戳记（GitHub/Twitter/Discord/Google 等）仅计入用户显式勾选的声明项。"
)
_IDENTITY_FALLBACK_NOTE = "实时链上身份核验当前不可达或处于离线测试模式，已回退至静态演示评估结构。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/identity", tags=["identity"])


class IdentityEvaluateRequest(BaseModel):
    wallet_address: str = Field(
        ...,
        min_length=10,
        max_length=64,
        description="待评估人机身份的 EVM 钱包地址",
    )
    declared_stamps: list[str] | None = Field(
        default=None,
        description="用户显式声明已持有的链下 OAuth / ZK 戳记 ID 列表（如 stamp_github、stamp_twitter）",
    )


@router.post("/evaluate", summary="核验并评估指定钱包的人机身份凭证与 Gitcoin Passport 得分")
async def evaluate_identity(req: IdentityEvaluateRequest) -> dict[str, Any]:
    result, is_live = await evaluate_wallet_identity_live(
        req.wallet_address,
        declared_stamps=req.declared_stamps,
    )
    if is_live:
        return mark_real({"ok": True, "data": result}, note=_IDENTITY_LIVE_NOTE)
    return mark_simulated({"ok": True, "data": result}, note=_IDENTITY_FALLBACK_NOTE)


@router.get("/stamping-guide", summary="获取按性价比（分值/成本）排序的推荐盖戳清单")
def get_guide() -> dict[str, Any]:
    guide = get_stamping_guide()
    return mark_simulated(
        {"ok": True, "data": {"guide": guide, "total": len(guide)}},
        note="盖戳指南为真实知识性目录（成本/权重为近似参考），不涉及个人数据模拟。",
    )
