"""Sybil Lineage & Fund Linkage Graph API Router (多钱包隔离自查与教学图谱路由).

POST /api/v1/lineage/detect

诚实口径：真实资金血缘检测需要链上转账数据源；接入前本端点只做结构性自查
（基于用户显式声明的关联）与隔离教学，整体打 ``simulated`` 标记。
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.sybil_lineage_graph import analyze_wallet_lineage
from app.utils.data_quality import mark_simulated

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/lineage", tags=["lineage"])


class DeclaredLink(BaseModel):
    source: str = Field(..., description="关联一方钱包地址 (0x...)")
    target: str = Field(..., description="关联另一方钱包地址 (0x...)")
    label: str = Field("", description="关联说明（如：误转、同源母号）")


class LineageDetectRequest(BaseModel):
    wallet_addresses: list[str] = Field(
        ...,
        min_length=1,
        max_length=50,
        description="待自查的多钱包地址列表 (至少 1 个，推荐 2-20 个)",
    )
    declared_links: list[DeclaredLink] | None = Field(
        default=None,
        description="用户自行声明的钱包间关联；服务端不猜测链上事实，只处理显式声明",
    )


@router.post("/detect", summary="多钱包结构性隔离自查与防关联教学图谱")
def detect_sybil_lineage(req: LineageDetectRequest) -> dict[str, Any]:
    """结构自查 + 教学红线；不编造链上发现，整体数据为模拟/教学口径."""
    result = analyze_wallet_lineage(
        req.wallet_addresses,
        declared_links=[link.model_dump() for link in req.declared_links] if req.declared_links else None,
    )
    return mark_simulated(
        result,
        note="无链上数据源：本端点仅做结构性自查（基于你显式声明的关联）与隔离教学，不包含真实的链上血缘检测。",
    )
