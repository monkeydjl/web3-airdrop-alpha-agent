"""Gas Alert Engine (全链 Gas 异动智能预警与阈值规则引擎).

允许空投猎人配置链上 Gas 阈值规则（极低交互窗口 / 拥堵防夹警报），动态扫描并输出即时告警。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Literal
import structlog

from app.services.gas_tracker import get_all_chains_gas_summary, get_chain_gas_status

logger = structlog.get_logger(__name__)

# 预设推荐规则
_DEFAULT_RULES: list[dict[str, Any]] = [
    {
        "id": "rule-eth-low",
        "chain": "ethereum",
        "condition": "below",
        "threshold_gwei": 12.0,
        "label": "以太坊主网黄金交互窗口 (Gas < 12 Gwei)",
        "enabled": True,
        "created_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": "rule-eth-high",
        "chain": "ethereum",
        "condition": "above",
        "threshold_gwei": 35.0,
        "label": "以太坊主网严重拥堵避险 (Gas > 35 Gwei)",
        "enabled": True,
        "created_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": "rule-arb-low",
        "chain": "arbitrum",
        "condition": "below",
        "threshold_gwei": 0.05,
        "label": "Arbitrum 超低费率批量交互 (Gas < 0.05 Gwei)",
        "enabled": True,
        "created_at": "2026-09-01T00:00:00Z",
    },
    {
        "id": "rule-base-low",
        "chain": "base",
        "condition": "below",
        "threshold_gwei": 0.01,
        "label": "Base 极速打卡时段 (Gas < 0.01 Gwei)",
        "enabled": True,
        "created_at": "2026-09-01T00:00:00Z",
    },
]

# 内存规则存储（支持用户动态增删改查）
_RULES_STORE: list[dict[str, Any]] = list(_DEFAULT_RULES)


def get_all_rules() -> list[dict[str, Any]]:
    """获取所有已配置的 Gas 告警规则."""
    return list(_RULES_STORE)


def create_rule(
    chain: str,
    condition: Literal["below", "above"],
    threshold_gwei: float,
    label: str,
    enabled: bool = True,
) -> dict[str, Any]:
    """创建一条新的 Gas 阈值告警规则."""
    rule_id = f"rule-{chain.lower()}-{uuid.uuid4().hex[:6]}"
    new_rule = {
        "id": rule_id,
        "chain": chain.lower().strip(),
        "condition": condition,
        "threshold_gwei": float(threshold_gwei),
        "label": label.strip() or f"{chain.upper()} Gas {condition} {threshold_gwei} Gwei",
        "enabled": enabled,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _RULES_STORE.append(new_rule)
    return new_rule


def delete_rule(rule_id: str) -> bool:
    """根据 ID 删除告警规则."""
    global _RULES_STORE
    initial_len = len(_RULES_STORE)
    _RULES_STORE = [r for r in _RULES_STORE if r["id"] != rule_id]
    return len(_RULES_STORE) < initial_len


def toggle_rule(rule_id: str, enabled: bool) -> dict[str, Any] | None:
    """切换告警规则启用状态."""
    for r in _RULES_STORE:
        if r["id"] == rule_id:
            r["enabled"] = enabled
            return r
    return None


def reset_rules_to_default() -> None:
    """重置为默认规则集."""
    global _RULES_STORE
    _RULES_STORE = list(_DEFAULT_RULES)


def evaluate_active_alerts(custom_gas_summary: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """比对当前实时 Gas 与已启用的规则，输出触发中的告警列表."""
    gas_summary = custom_gas_summary or get_all_chains_gas_summary()
    chains_data = gas_summary.get("data", {})

    active_alerts: list[dict[str, Any]] = []

    for rule in _RULES_STORE:
        if not rule.get("enabled", True):
            continue

        chain = rule["chain"]
        chain_info = chains_data.get(chain)
        if not chain_info:
            continue

        current_gwei = float(chain_info.get("gas_gwei", 0.0))
        condition = rule["condition"]
        threshold = rule["threshold_gwei"]
        is_triggered = False

        if condition == "below" and current_gwei <= threshold:
            is_triggered = True
        elif condition == "above" and current_gwei >= threshold:
            is_triggered = True

        if is_triggered:
            severity = "success" if condition == "below" else "warning"
            action = "适合进行高价值链上交互与批量转账" if condition == "below" else "建议暂时避开或调低滑点"
            message = (
                f"⚡ [{chain.upper()}] 当前实时 Gas 仅 {current_gwei} Gwei "
                f"(低于阈值 {threshold} Gwei)，{action}！"
                if condition == "below"
                else f"🚨 [{chain.upper()}] 当前实时 Gas 达到 {current_gwei} Gwei "
                f"(超出设定阈值 {threshold} Gwei)，{action}！"
            )

            active_alerts.append({
                "rule_id": rule["id"],
                "label": rule["label"],
                "chain": chain,
                "current_gwei": current_gwei,
                "threshold_gwei": threshold,
                "condition": condition,
                "severity": severity,
                "message": message,
                "triggered_at": datetime.now(timezone.utc).isoformat(),
            })

    return active_alerts
