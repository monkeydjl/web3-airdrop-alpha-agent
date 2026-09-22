"""Gas Tracker Router (全链 Gas 实时监控路由).

GET /api/v1/gas/summary
GET /api/v1/gas/{chain}
"""

from typing import Any
from fastapi import APIRouter, Path, Query
import structlog

from app.services.gas_tracker import (
    get_all_chains_gas_summary,
    get_chain_gas_status,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/gas", tags=["gas"])


@router.get("/summary", summary="获取全链实时 Gas 概览与黄金交互时段预测")
def get_gas_summary() -> dict[str, Any]:
    """返回所有支持链的实时 Gas 详情与交互窗口建议."""
    return get_all_chains_gas_summary()


@router.get("/{chain}", summary="获取单链实时 Gas 状态")
def get_single_chain_gas(
    chain: str = Path(..., description="公链标识 (ethereum, arbitrum, base, optimism, polygon, bsc)"),
    refresh: bool = Query(False, description="是否强制刷新缓存"),
) -> dict[str, Any]:
    """返回指定链的当前 Gas 详情."""
    data = get_chain_gas_status(chain.lower().strip(), force_refresh=refresh)
    return {"ok": True, "data": data}
