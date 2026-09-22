"""Web3 Identity & Passport Radar API Router.

POST /api/v1/identity/evaluate
GET  /api/v1/identity/stamping-guide
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.identity_passport_radar import evaluate_wallet_identity, get_stamping_guide

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
    return {"ok": True, "data": result}


@router.get("/stamping-guide", summary="获取按性价比（分值/成本）排序的推荐盖戳清单")
def get_guide() -> dict[str, Any]:
    guide = get_stamping_guide()
    return {"ok": True, "data": {"guide": guide, "total": len(guide)}}
