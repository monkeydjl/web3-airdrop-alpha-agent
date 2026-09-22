"""Gas Tracker Router (全链 Gas 实时监控与阈值预警路由).

GET /api/v1/gas/summary
GET /api/v1/gas/alerts/rules
POST /api/v1/gas/alerts/rules
DELETE /api/v1/gas/alerts/rules/{rule_id}
PATCH /api/v1/gas/alerts/rules/{rule_id}
GET /api/v1/gas/alerts/active
GET /api/v1/gas/{chain}
"""

from typing import Any, Literal
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field
import structlog

from app.services.gas_tracker import (
    get_all_chains_gas_summary,
    get_chain_gas_status,
)
from app.services.gas_alert_engine import (
    get_all_rules,
    create_rule,
    delete_rule,
    toggle_rule,
    evaluate_active_alerts,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/gas", tags=["gas"])


class CreateGasRuleRequest(BaseModel):
    chain: str = Field(..., description="公链名称 (ethereum, arbitrum, base, optimism, polygon, bsc)")
    condition: Literal["below", "above"] = Field(..., description="触发条件: below (低于) 或 above (高于)")
    threshold_gwei: float = Field(..., gt=0, description="Gas 阈值 (Gwei)")
    label: str = Field("", description="规则标签与备注说明")
    enabled: bool = Field(True, description="是否立即启用")


class ToggleGasRuleRequest(BaseModel):
    enabled: bool = Field(..., description="是否启用")


@router.get("/summary", summary="获取全链实时 Gas 概览与黄金交互时段预测")
def get_gas_summary() -> dict[str, Any]:
    """返回所有支持链的实时 Gas 详情与交互窗口建议."""
    return get_all_chains_gas_summary()


@router.get("/alerts/rules", summary="获取配置的 Gas 告警规则列表")
def list_gas_alert_rules() -> dict[str, Any]:
    """返回当前所有的 Gas 预警监控规则."""
    rules = get_all_rules()
    return {"ok": True, "count": len(rules), "data": rules}


@router.post("/alerts/rules", summary="新增一条 Gas 阈值告警规则")
def add_gas_alert_rule(req: CreateGasRuleRequest) -> dict[str, Any]:
    """创建自定义的 Gas 波动监控规则."""
    rule = create_rule(
        chain=req.chain,
        condition=req.condition,
        threshold_gwei=req.threshold_gwei,
        label=req.label,
        enabled=req.enabled,
    )
    return {"ok": True, "data": rule}


@router.delete("/alerts/rules/{rule_id}", summary="删除一条 Gas 告警规则")
def remove_gas_alert_rule(
    rule_id: str = Path(..., description="规则 ID"),
) -> dict[str, Any]:
    """删除指定的告警规则."""
    success = delete_rule(rule_id)
    if not success:
        raise HTTPException(status_code=404, detail="规则不存在或已删除")
    return {"ok": True, "message": "规则已成功删除"}


@router.patch("/alerts/rules/{rule_id}", summary="切换规则启用/禁用状态")
def switch_gas_alert_rule(
    rule_id: str = Path(..., description="规则 ID"),
    req: ToggleGasRuleRequest = ...,
) -> dict[str, Any]:
    """修改指定规则的启用开关."""
    updated = toggle_rule(rule_id, req.enabled)
    if not updated:
        raise HTTPException(status_code=404, detail="规则未找到")
    return {"ok": True, "data": updated}


@router.get("/alerts/active", summary="获取当前触发中的 Gas 即时告警")
def get_active_gas_alerts() -> dict[str, Any]:
    """对比全链实时 Gas 与规则库，返回当前正在触发的预警通知."""
    alerts = evaluate_active_alerts()
    return {"ok": True, "count": len(alerts), "data": alerts}


@router.get("/{chain}", summary="获取单链实时 Gas 状态")
def get_single_chain_gas(
    chain: str = Path(..., description="公链标识 (ethereum, arbitrum, base, optimism, polygon, bsc)"),
    refresh: bool = Query(False, description="是否强制刷新缓存"),
) -> dict[str, Any]:
    """返回指定链的当前 Gas 详情."""
    data = get_chain_gas_status(chain.lower().strip(), force_refresh=refresh)
    return {"ok": True, "data": data}
