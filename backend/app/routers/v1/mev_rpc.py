"""MEV RPC & Private Mempool Protection API Router.

GET  /api/v1/mev-rpc/nodes
POST /api/v1/mev-rpc/benchmark
"""

from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.mev_rpc_sentinel import benchmark_rpc_node, list_mev_rpc_nodes
from app.utils.data_quality import mark_simulated

_MEV_NOTE = "节点清单为真实公共服务；「延迟探测」返回预设估值（未真实发包测速）。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/mev-rpc", tags=["mev-rpc"])


class MevBenchmarkRequest(BaseModel):
    node_id: str | None = Field(default=None, description="预设私有 RPC 节点 ID")
    custom_url: str | None = Field(default=None, description="自定义 RPC 节点 URL")


@router.get("/nodes", summary="获取所有受支持的防 MEV 私有 RPC 节点列表与特性")
def get_mev_rpc_nodes(chain_id: int | None = None) -> dict[str, Any]:
    nodes = list_mev_rpc_nodes(chain_id)
    return mark_simulated(
        {"ok": True, "data": {"nodes": nodes, "total": len(nodes)}},
        note=_MEV_NOTE,
    )


@router.post("/benchmark", summary="探测指定或自定义 RPC 节点的延迟与防护等级")
def benchmark_rpc(req: MevBenchmarkRequest) -> dict[str, Any]:
    result = benchmark_rpc_node(node_id=req.node_id, custom_url=req.custom_url)
    return mark_simulated({"ok": True, "data": result}, note=_MEV_NOTE)
