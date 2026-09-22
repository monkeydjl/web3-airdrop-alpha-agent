"""Contract Calldata Decoder API Router (合约 Calldata 解码与安全沙箱路由).

POST /api/v1/calldata/decode
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.calldata_decoder import decode_calldata

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/calldata", tags=["calldata"])


class CalldataDecodeRequest(BaseModel):
    contract_address: str = Field(..., description="目标智能合约地址 (0x...)")
    calldata: str = Field(..., description="待逆向解析的十六进制 Calldata 数据流")
    value_eth: float = Field(0.0, ge=0.0, description="随交易发送的原生 ETH 数量")


@router.post("/decode", summary="逆向解码 Calldata 4-byte 签名、参数并进行安全性体检")
def parse_calldata(req: CalldataDecodeRequest) -> dict[str, Any]:
    """输入原始 Calldata，解构函数参数、分析无限授权与代理后门，输出人性化操作意图."""
    return decode_calldata(
        contract_address=req.contract_address,
        calldata=req.calldata,
        value_eth=req.value_eth,
    )
