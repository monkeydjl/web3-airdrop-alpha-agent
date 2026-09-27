"""Web3 Identity & Passport Radar API Router.

POST /api/v1/identity/evaluate
GET  /api/v1/identity/stamping-guide
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.identity_passport_radar import evaluate_wallet_identity, get_stamping_guide
from app.utils.data_quality import mark_simulated

_IDENTITY_NOTE = "戳记目录为真实知识；但个人得分基于地址哈希模拟（未接 Gitcoin Passport API），非链上真实凭证。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/identity", tags=["identity"])


class IdentityEvaluateRequest(BaseModel):
    wallet_address: str = Field(
        ...,
        min_length=10,
        max_length=64,
        description="待评估人机身份的 EVM 钱包地址",
    )


@router.post("/evaluate", summary="模拟评估指定钱包的人机身份凭证与 Gitcoin Passport 得分")
def evaluate_identity(req: IdentityEvaluateRequest) -> dict[str, Any]:
    result = evaluate_wallet_identity(req.wallet_address)
    return mark_simulated({"ok": True, "data": result}, note=_IDENTITY_NOTE)


@router.get("/stamping-guide", summary="获取按性价比（分值/成本）排序的推荐盖戳清单")
def get_guide() -> dict[str, Any]:
    guide = get_stamping_guide()
    return mark_simulated(
        {"ok": True, "data": {"guide": guide, "total": len(guide)}},
        note="盖戳指南为真实知识性目录（成本/权重为近似参考），不涉及个人数据模拟。",
    )
