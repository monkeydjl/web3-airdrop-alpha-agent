"""Multi-Operator Team Studio & Task Allocation Manager (多操作员协同与任务分配系统).

为多钱包矩阵、工作室和投研团队提供高效分工协作支持：
- 管理操作员（Operator）档案与名下专属钱包分配
- 按照协议和赛道为不同成员指派交互任务配额
- 实时追踪团队各成员的每日完成率、Gas 支出与履约进度
- 校验操作员之间的女巫隔离状态（严禁不同操作员私自交叉转账）。
"""

from __future__ import annotations

import time
from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 内存/默认操作员与任务团队数据库模拟
DEFAULT_OPERATORS: list[dict[str, Any]] = [
    {
        "operator_id": "op_alice",
        "name": "Alice (Core Hunter)",
        "role": "Lead Farmer",
        "assigned_wallets": 20,
        "assigned_projects": ["Scroll", "Monad", "Hyperliquid"],
        "today_completed_tx": 48,
        "today_target_tx": 60,
        "completion_rate": 0.80,
        "gas_spent_usd": 14.50,
        "status": "online",
        "ip_proxy_isolated": True,
        "last_active": "10 分钟前",
    },
    {
        "operator_id": "op_bob",
        "name": "Bob (DeFi & Staking)",
        "role": "Senior Operator",
        "assigned_wallets": 15,
        "assigned_projects": ["Linea", "Symbiotic", "Karak"],
        "today_completed_tx": 35,
        "today_target_tx": 45,
        "completion_rate": 0.78,
        "gas_spent_usd": 18.20,
        "status": "online",
        "ip_proxy_isolated": True,
        "last_active": "25 分钟前",
    },
    {
        "operator_id": "op_charlie",
        "name": "Charlie (Testnet Automator)",
        "role": "Testnet Specialist",
        "assigned_wallets": 30,
        "assigned_projects": ["Story Protocol", "Berachain", "Movement"],
        "today_completed_tx": 90,
        "today_target_tx": 90,
        "completion_rate": 1.00,
        "gas_spent_usd": 0.00,
        "status": "idle",
        "ip_proxy_isolated": True,
        "last_active": "1 小时前",
    },
]

DEFAULT_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "task_1",
        "title": "Scroll Canvas 批量补打徽章",
        "project": "Scroll",
        "operator_id": "op_alice",
        "target_wallet_count": 20,
        "status": "in_progress",
        "priority": "high",
        "deadline": "今日 24:00",
    },
    {
        "task_id": "task_2",
        "title": "Linea Voyage 积分冲刺",
        "project": "Linea",
        "operator_id": "op_bob",
        "target_wallet_count": 15,
        "status": "in_progress",
        "priority": "high",
        "deadline": "明日 12:00",
    },
    {
        "task_id": "task_3",
        "title": "Story Protocol 测试网合约铸造",
        "project": "Story Protocol",
        "operator_id": "op_charlie",
        "target_wallet_count": 30,
        "status": "completed",
        "priority": "medium",
        "deadline": "已完成",
    },
]


def get_team_studio_dashboard() -> dict[str, Any]:
    """获取工作室团队协同全局指标与操作员表现."""
    total_wallets = sum(int(op["assigned_wallets"]) for op in DEFAULT_OPERATORS)
    total_tx_today = sum(int(op["today_completed_tx"]) for op in DEFAULT_OPERATORS)
    total_target_today = sum(int(op["today_target_tx"]) for op in DEFAULT_OPERATORS)
    total_gas_usd = sum(float(op["gas_spent_usd"]) for op in DEFAULT_OPERATORS)
    
    avg_completion = (total_tx_today / total_target_today) if total_target_today > 0 else 0.0

    return {
        "timestamp": int(time.time()),
        "summary": {
            "team_name": "Alpha Hunter Studio Alpha-1",
            "active_operators_count": len(DEFAULT_OPERATORS),
            "total_managed_wallets": total_wallets,
            "today_total_transactions": total_tx_today,
            "overall_completion_rate": round(avg_completion, 2),
            "today_gas_budget_usd": round(total_gas_usd, 2),
            "sybil_isolation_rating": "100% (无跨操作员交叉转账，独立住宅静态 IP)",
        },
        "operators": DEFAULT_OPERATORS,
        "assigned_tasks": DEFAULT_TASKS,
    }


def assign_task_to_operator(
    title: str,
    project: str,
    operator_id: str,
    target_wallet_count: int,
    priority: str = "medium",
    deadline: str = "今日 24:00",
) -> dict[str, Any]:
    """为指定操作员派发新任务."""
    new_task = {
        "task_id": f"task_{int(time.time())}",
        "title": title.strip(),
        "project": project.strip(),
        "operator_id": operator_id.strip(),
        "target_wallet_count": max(1, target_wallet_count),
        "status": "pending",
        "priority": priority,
        "deadline": deadline,
        "created_at": int(time.time()),
    }
    DEFAULT_TASKS.append(new_task)
    return {"success": True, "task": new_task}


def register_or_update_operator(
    operator_id: str,
    name: str,
    role: str = "Operator",
    assigned_wallets: int = 10,
    assigned_projects: list[str] | None = None,
) -> dict[str, Any]:
    """新增或更新操作员信息."""
    projects = assigned_projects or ["Scroll"]
    existing = next((op for op in DEFAULT_OPERATORS if op["operator_id"] == operator_id), None)
    
    if existing:
        existing["name"] = name
        existing["role"] = role
        existing["assigned_wallets"] = assigned_wallets
        existing["assigned_projects"] = projects
        return {"action": "updated", "operator": existing}
    
    new_op = {
        "operator_id": operator_id,
        "name": name,
        "role": role,
        "assigned_wallets": assigned_wallets,
        "assigned_projects": projects,
        "today_completed_tx": 0,
        "today_target_tx": assigned_wallets * 3,
        "completion_rate": 0.0,
        "gas_spent_usd": 0.0,
        "status": "online",
        "ip_proxy_isolated": True,
        "last_active": "刚刚",
    }
    DEFAULT_OPERATORS.append(new_op)
    return {"action": "created", "operator": new_op}
