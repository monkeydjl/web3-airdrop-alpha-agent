"""Wallet Health & Activity Diagnostic API Router (钱包交互广度与健康度诊断路由).

POST /api/v1/diagnostic/wallet
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.wallet_activity_diagnostic import diagnose_wallet_health
from app.utils.data_quality import mark_simulated

_DIAGNOSTIC_NOTE = (
    "未提供链上参数时，缺失维度基于地址哈希模拟生成（非链上真实数据）；"
    "请在高级参数中填入真实的活跃月数/交易数/合约数以获得基于事实的评分。"
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/diagnostic", tags=["diagnostic"])


class WalletDiagnosticRequest(BaseModel):
    wallet_address: str = Field(..., description="待检测的 EVM 钱包地址 (0x...)")
    active_months: int | None = Field(None, ge=1, le=60, description="活跃自然月数")
    tx_count: int | None = Field(None, ge=1, description="累计交易笔数")
    unique_contracts: int | None = Field(None, ge=1, description="交互的独立合约数量")
    protocol_types: list[str] | None = Field(
        None, description="交互过的赛道类别 (dex, lending, bridge, nft, governance)"
    )
    total_gas_spent_eth: float | None = Field(None, ge=0, description="累计消耗 Gas (ETH)")
    chains_active: list[str] | None = Field(None, description="活跃的公链列表")


@router.post("/wallet", summary="执行 5 维钱包链上交互广度与反女巫健康度诊断")
def scan_wallet_health(req: WalletDiagnosticRequest) -> dict[str, Any]:
    """对钱包活跃月份、合约深度、赛道分布、Gas 投入及跨链印记进行全方位体检，并提供补刀指南."""
    result = diagnose_wallet_health(
        wallet_address=req.wallet_address,
        active_months=req.active_months,
        tx_count=req.tx_count,
        unique_contracts=req.unique_contracts,
        protocol_types=req.protocol_types,
        total_gas_spent_eth=req.total_gas_spent_eth,
        chains_active=req.chains_active,
    )
    # 诚实打标：有任何维度靠哈希模拟补齐时，必须告知用户哪些输入是编的
    missing_inputs = [
        field
        for field, val in (
            ("active_months", req.active_months),
            ("tx_count", req.tx_count),
            ("unique_contracts", req.unique_contracts),
            ("total_gas_spent_eth", req.total_gas_spent_eth),
        )
        if val is None
    ]
    if missing_inputs:
        result = mark_simulated(result, note=f"缺失维度由地址哈希模拟：{', '.join(missing_inputs)}。{_DIAGNOSTIC_NOTE}")
    return result
