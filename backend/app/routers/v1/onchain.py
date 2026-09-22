"""On-chain public EVM RPC inspection router.

Provides endpoints to verify contract deployment and activity across testnets and mainnet
using 100% keyless, free public RPC nodes.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.public_rpc_verifier import (
    SUPPORTED_CHAINS,
    is_valid_evm_address,
    verify_contract_liveness,
)

router = APIRouter(tags=["onchain"])


class VerifyContractRequest(BaseModel):
    address: str = Field(..., description="EVM 合约或钱包地址 (0x 开头 40 位十六进制)")
    chain: str = Field("sepolia", description="目标网络代号 (如 sepolia, arbitrum_sepolia, berachain_bartio)")


@router.get(
    "/onchain/chains",
    summary="获取支持的免 Key 公共 RPC 链列表",
    description="返回当前系统支持的全部免费免鉴权测试网与主网列表及链 ID。",
)
def list_supported_chains() -> dict[str, Any]:
    chains_data = []
    for key, val in SUPPORTED_CHAINS.items():
        chains_data.append(
            {
                "key": key,
                "name": val["name"],
                "type": val["type"],
                "chain_id": val["chain_id"],
                "endpoint_count": len(val["endpoints"]),
            }
        )
    return {
        "ok": True,
        "data": chains_data,
    }


@router.post(
    "/onchain/verify",
    summary="使用免 Key 公共 RPC 探测合约存活性",
    description="通过公共 RPC 节点调用 eth_getCode 与 eth_getTransactionCount，校验地址是否已部署字节码及链上交互活跃度。",
)
async def verify_onchain_address(payload: VerifyContractRequest) -> dict[str, Any]:
    if not is_valid_evm_address(payload.address):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_ADDRESS",
                "message": "Invalid EVM address format (must be 0x followed by 40 hex characters)",
            },
        )

    res = await verify_contract_liveness(payload.address, chain=payload.chain)
    return {
        "ok": True,
        "data": res,
    }


class SybilCheckRequest(BaseModel):
    addresses: list[str] = Field(..., min_length=1, max_length=20, description="需要自检的 EVM 钱包地址列表")


@router.post(
    "/onchain/sybil-check",
    summary="多钱包女巫关联风险自检雷达",
    description="对用户提交的钱包地址矩阵进行女巫风险关联性分析，评估地址特征与隔离风险。",
)
def check_sybil_risk(payload: SybilCheckRequest) -> dict[str, Any]:
    from app.services.onchain_sybil import evaluate_sybil_risk

    result = evaluate_sybil_risk(payload.addresses)
    return {"ok": True, "data": result}


@router.get(
    "/onchain/sybil-topology",
    summary="获取多钱包防女巫资金隔离路由拓扑图",
    description="生成标准 0 关联资金流拓扑结构、节点信息与 Mermaid 流程图。",
)
def get_sybil_topology(
    wallet_count: int = 3,
    project_name: str = "Airdrop Project",
) -> dict[str, Any]:
    from app.services.onchain_sybil import generate_sybil_routing_topology

    topo = generate_sybil_routing_topology(wallet_count=wallet_count, project_name=project_name)
    return {"ok": True, "data": topo.to_dict()}

