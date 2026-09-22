"""Sybil Defense Dossier Router (防女巫申诉存证报告路由).

POST /api/v1/sybil/generate-dossier
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.sybil_defense_dossier import generate_sybil_defense_dossier

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/sybil", tags=["sybil"])


class DossierRequest(BaseModel):
    wallet_address: str = Field(..., description="申诉目标钱包 EVM 地址 (0x...)")
    project_name: str = Field("LayerZero", description="申诉项目名称，如 LayerZero, Linea, ZKsync")
    appeal_reason: str = Field("False-positive sybil identification", description="申诉核心理由")
    custom_notes: str = Field("", description="用户附加备注说明")


@router.post("/generate-dossier", summary="一键生成标准化防女巫申诉存证报告")
def create_dossier(req: DossierRequest) -> dict[str, Any]:
    """生成防女巫独立参与者自证报告与 Markdown 文档."""
    result = generate_sybil_defense_dossier(
        wallet_address=req.wallet_address,
        project_name=req.project_name,
        appeal_reason=req.appeal_reason,
        custom_notes=req.custom_notes,
    )
    return {
        "ok": True,
        "data": result,
    }
