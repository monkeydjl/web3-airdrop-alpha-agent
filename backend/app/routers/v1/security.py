"""Security Sentinel Router (智能合约与代币授权安全风控路由).

POST /api/v1/security/approvals
POST /api/v1/security/domain-check
POST /api/v1/security/poison-tokens
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.security_sentinel import (
    check_domain_safety,
    scan_dust_poison_tokens_live,
    scan_token_approvals_live,
)
from app.utils.data_quality import mark_real, mark_simulated

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/security", tags=["security"])


class ApprovalsRequest(BaseModel):
    wallet_address: str = Field(..., description="钱包地址 (0x...)")
    chain_id: str = Field("1", description="链 ID（默认 1=Ethereum，可选 42161/8453/10/137）")


class DomainCheckRequest(BaseModel):
    url: str = Field(..., description="项目官网或交互链接 URL")


@router.post("/approvals", summary="扫描钱包授权风险健康度")
async def check_wallet_approvals(req: ApprovalsRequest) -> dict[str, Any]:
    """扫描钱包代币授权暴露风险并给出 Revoke 建议（优先 GoPlus 实时查询，离线/失败诚实降级为 simulated）。"""
    data, is_live = await scan_token_approvals_live(req.wallet_address, chain_id=req.chain_id)
    if is_live:
        return mark_real({"ok": True, "data": data}, note="数据来自 GoPlus Security 实时链上授权风控 API")
    return mark_simulated(
        {"ok": True, "data": data},
        note="GoPlus 实时风控当前不可用或处于离线测试模式，已回退至静态样本结构",
    )


@router.post("/domain-check", summary="检测项目官网防钓鱼与同形异义词安全")
def check_url(req: DomainCheckRequest) -> dict[str, Any]:
    """检测 URL 是否为山寨假冒或钓鱼站点."""
    data = check_domain_safety(req.url)
    return {"ok": True, "data": data}


@router.post("/poison-tokens", summary="嗅探排查钱包钓鱼下毒空投代币")
async def check_poison_tokens(req: ApprovalsRequest) -> dict[str, Any]:
    """排查下毒代币与恶意地址标记（优先 GoPlus 实时查询，离线/失败诚实降级为 simulated）。"""
    data, is_live = await scan_dust_poison_tokens_live(req.wallet_address, chain_id=req.chain_id)
    if is_live:
        return mark_real({"ok": True, "data": data}, note="数据来自 GoPlus Security 实时地址风控 API")
    return mark_simulated(
        {"ok": True, "data": data},
        note="GoPlus 实时风控当前不可用或处于离线测试模式，已回退至静态样本结构",
    )
