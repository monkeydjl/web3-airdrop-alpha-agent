"""MEV RPC & Private Mempool Protection API Router.

GET  /api/v1/mev-rpc/nodes
POST /api/v1/mev-rpc/benchmark
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.mev_rpc_sentinel import benchmark_rpc_node_live, list_mev_rpc_nodes
from app.services.vitals import BlockedTargetError
from app.utils.data_quality import mark_real, mark_simulated

_MEV_NODES_NOTE = (
    "节点清单为真实公共防夹服务，默认延迟字段为静态参考估值；"
    "请调用 POST /api/v1/mev-rpc/benchmark 获取实时链上往返延迟。"
)
_MEV_FALLBACK_NOTE = "实时 JSON-RPC 测速当前不可达或处于离线测试模式，已回退至预设延迟估值。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/mev-rpc", tags=["mev-rpc"])


class MevBenchmarkRequest(BaseModel):
    node_id: str | None = Field(default=None, description="预设私有 RPC 节点 ID")
    custom_url: str | None = Field(default=None, description="自定义 RPC 节点 URL（仅限公网 https://）")


@router.get("/nodes", summary="获取所有受支持的防 MEV 私有 RPC 节点列表与特性")
def get_mev_rpc_nodes(chain_id: int | None = None) -> dict[str, Any]:
    nodes = list_mev_rpc_nodes(chain_id)
    return mark_simulated(
        {"ok": True, "data": {"nodes": nodes, "total": len(nodes)}},
        note=_MEV_NODES_NOTE,
    )


@router.post("/benchmark", summary="探测指定或自定义 RPC 节点的延迟与防护等级")
async def benchmark_rpc(req: MevBenchmarkRequest) -> dict[str, Any]:
    try:
        result, is_live = await benchmark_rpc_node_live(
            node_id=req.node_id,
            custom_url=req.custom_url,
        )
    except BlockedTargetError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_RPC_URL",
                "message": "Custom RPC URL must be a valid public https:// endpoint",
            },
        ) from exc

    if is_live:
        return mark_real(
            {"ok": True, "data": result},
            note="来自实时 JSON-RPC (eth_blockNumber) 节点往返测速。",
        )
    return mark_simulated({"ok": True, "data": result}, note=_MEV_FALLBACK_NOTE)
