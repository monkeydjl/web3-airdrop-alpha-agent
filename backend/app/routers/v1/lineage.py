"""Sybil Lineage & Fund Linkage Graph API Router (多地址女巫资金血缘图谱路由).

POST /api/v1/lineage/detect
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.sybil_lineage_graph import analyze_wallet_lineage

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/lineage", tags=["lineage"])


class LineageDetectRequest(BaseModel):
    wallet_addresses: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="待检测的多钱包地址列表 (至少 1 个，推荐 2-20 个)",
    )


@router.post("/detect", summary="执行多钱包资金血缘与有向图女巫拓扑检测")
def detect_sybil_lineage(req: LineageDetectRequest) -> dict[str, Any]:
    """输入多个钱包地址，排查直接互转、共同母号出资与同一充值归集等连通分支特征，返回拓扑图谱与隔离评分."""
    return analyze_wallet_lineage(req.wallet_addresses)
