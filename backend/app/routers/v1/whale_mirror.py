"""Whale Mirror Airdrop Backtester API Router.

GET  /api/v1/whale-mirror/benchmarks
POST /api/v1/whale-mirror/compare
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.whale_mirror_backtester import compare_wallet_with_whale, list_whale_benchmarks

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/whale-mirror", tags=["whale-mirror"])


class WhaleCompareRequest(BaseModel):
    benchmark_id: str = Field(default="arbitrum_top_tier", description="对标的顶级空投基准 ID")
    user_active_months: int = Field(default=4, ge=1, le=48, description="当前钱包活跃月数")
    user_total_txs: int = Field(default=25, ge=1, le=5000, description="当前累计交互笔数")
    user_contracts: int = Field(default=12, ge=1, le=1000, description="交互独立合约数量")
    user_bridged_usd: float = Field(default=3200.0, ge=0.0, description="累计跨链流水 (USD)")
    user_retained_eth: float = Field(default=0.02, ge=0.0, description="当前钱包留存余额 (ETH)")
    target_project: str = Field(default="Monad", description="目标执行作业项目名称")


@router.get("/benchmarks", summary="获取所有历史顶级空投胜利者行为基准")
def get_benchmarks() -> dict[str, Any]:
    benchmarks = list_whale_benchmarks()
    return {"ok": True, "data": {"benchmarks": benchmarks, "total": len(benchmarks)}}


@router.post("/compare", summary="对比本地钱包与顶级巨鲸标准并生成补刀清单")
def compare_with_whale(req: WhaleCompareRequest) -> dict[str, Any]:
    result = compare_wallet_with_whale(
        benchmark_id=req.benchmark_id,
        user_active_months=req.user_active_months,
        user_total_txs=req.user_total_txs,
        user_contracts=req.user_contracts,
        user_bridged_usd=req.user_bridged_usd,
        user_retained_eth=req.user_retained_eth,
        target_project=req.target_project,
    )
    return {"ok": True, "data": result}
