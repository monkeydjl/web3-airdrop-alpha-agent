"""Security Sentinel Router (智能合约与代币授权安全风控路由).

POST /api/v1/security/approvals
POST /api/v1/security/domain-check
POST /api/v1/security/poison-tokens
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.security_sentinel import (
    check_domain_safety,
    scan_dust_poison_tokens,
    scan_token_approvals,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/security", tags=["security"])


class ApprovalsRequest(BaseModel):
    wallet_address: str = Field(..., description="钱包地址 (0x...)")


class DomainCheckRequest(BaseModel):
    url: str = Field(..., description="项目官网或交互链接 URL")


@router.post("/approvals", summary="扫描钱包授权风险健康度")
def check_wallet_approvals(req: ApprovalsRequest) -> dict[str, Any]:
    """扫描钱包代币授权暴露风险并给出 Revoke 建议."""
    data = scan_token_approvals(req.wallet_address)
    return {"ok": True, "data": data}


@router.post("/domain-check", summary="检测项目官网防钓鱼与同形异义词安全")
def check_url(req: DomainCheckRequest) -> dict[str, Any]:
    """检测 URL 是否为山寨假冒或钓鱼站点."""
    data = check_domain_safety(req.url)
    return {"ok": True, "data": data}


@router.post("/poison-tokens", summary="嗅探排查钱包钓鱼下毒空投代币")
def check_poison_tokens(req: ApprovalsRequest) -> dict[str, Any]:
    """排查下毒代币."""
    data = scan_dust_poison_tokens(req.wallet_address)
    return {"ok": True, "data": data}
