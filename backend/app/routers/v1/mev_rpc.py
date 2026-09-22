"""MEV RPC & Private Mempool Protection API Router.

GET  /api/v1/mev-rpc/nodes
POST /api/v1/mev-rpc/benchmark
"""

from typing import Any
from fastapi import APIRouter
from pydantic import BaseModel, Field
import structlog

from app.services.mev_rpc_sentinel import benchmark_rpc_node, list_mev_rpc_nodes

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/mev-rpc", tags=["mev-rpc"])


class MevBenchmarkRequest(BaseModel):
    node_id: str | None = Field(default=None, description="预设私有 RPC 节点 ID")
    custom_url: str | None = Field(default=None, description="自定义 RPC 节点 URL")


@router.get("/nodes", summary="获取所有受支持的防 MEV 私有 RPC 节点列表与特性")
def get_mev_rpc_nodes(chain_id: int | None = None) -> dict[str, Any]:
    nodes = list_mev_rpc_nodes(chain_id)
    return {"ok": True, "data": {"nodes": nodes, "total": len(nodes)}}


@router.post("/benchmark", summary="探测指定或自定义 RPC 节点的延迟与防护等级")
def benchmark_rpc(req: MevBenchmarkRequest) -> dict[str, Any]:
    result = benchmark_rpc_node(node_id=req.node_id, custom_url=req.custom_url)
    return {"ok": True, "data": result}
