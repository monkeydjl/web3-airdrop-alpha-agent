"""Multi-Operator Team Studio & Task Allocation Manager (多操作员协同与任务分配).

诚实口径（2026-09-23 审计，docs/EXPANSION_AUDIT_REPORT.md）：

此服务历史上内置 Alice/Bob/Charlie 三个**编造的操作员**（含虚构的今日完成
tx 数、Gas 支出与「100% 隔离合规」评级），把演示数据冒充团队实况。已清理：

- 不再内置任何虚构操作员/任务——新用户从空态开始，自行录入团队。
- 「隔离合规审计」评级在无真实链上/操作日志数据源前不输出（保持 None）。

持久化（2026-09-23，审计报告 P1）：操作员与任务此前存模块级内存列表
（重启即失，且多 worker 进程各看各的团队）。现沿用 faucet_claims 的同款
模式落 SQLite（``ensure_team_studio_tables`` + 可选 ``conn`` 注入），
函数签名与返回形态保持兼容。今日完成 tx / Gas 等运行时指标仍由
``update_operator_stats`` 显式更新，不编造。
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from app.db import DbConnection, connection_scope

logger = structlog.get_logger(__name__)

_OPERATORS_TABLE = "team_studio_operators"
_TASKS_TABLE = "team_studio_tasks"

_OPERATOR_COLS = (
    "operator_id, name, role, assigned_wallets, assigned_projects, "
    "today_completed_tx, today_target_tx, completion_rate, gas_spent_usd, "
    "status, ip_proxy_isolated, last_active, updated_at"
)

_TASK_COLS = "task_id, title, project, operator_id, target_wallet_count, status, priority, deadline, created_at"


def ensure_team_studio_tables(conn: DbConnection) -> None:
    """Ensure team_studio_operators / team_studio_tasks tables and indexes exist."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_OPERATORS_TABLE} (
            operator_id        TEXT PRIMARY KEY,
            name               TEXT NOT NULL,
            role               TEXT NOT NULL DEFAULT 'Operator',
            assigned_wallets   INTEGER NOT NULL DEFAULT 10,
            assigned_projects  TEXT NOT NULL DEFAULT '[]',
            today_completed_tx INTEGER NOT NULL DEFAULT 0,
            today_target_tx    INTEGER NOT NULL DEFAULT 0,
            completion_rate    REAL NOT NULL DEFAULT 0.0,
            gas_spent_usd      REAL NOT NULL DEFAULT 0.0,
            status             TEXT NOT NULL DEFAULT 'idle',
            ip_proxy_isolated  INTEGER,
            last_active        TEXT,
            updated_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_TASKS_TABLE} (
            task_id             TEXT PRIMARY KEY,
            title               TEXT NOT NULL,
            project             TEXT NOT NULL,
            operator_id         TEXT NOT NULL,
            target_wallet_count INTEGER NOT NULL DEFAULT 1,
            status              TEXT NOT NULL DEFAULT 'pending',
            priority            TEXT NOT NULL DEFAULT 'medium',
            deadline            TEXT,
            created_at          INTEGER NOT NULL
        );
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_team_studio_tasks_operator ON {_TASKS_TABLE}(operator_id, status);")
    conn.commit()


def _row_to_operator(row: Any) -> dict[str, Any]:
    """容忍 dict / sqlite3.Row / tuple 三种行形态（与 faucet_registry 同款）。"""
    if hasattr(row, "keys") or isinstance(row, dict):
        d = dict(row)
    else:
        d = {
            "operator_id": row[0],
            "name": row[1],
            "role": row[2],
            "assigned_wallets": row[3],
            "assigned_projects": row[4],
            "today_completed_tx": row[5],
            "today_target_tx": row[6],
            "completion_rate": row[7],
            "gas_spent_usd": row[8],
            "status": row[9],
            "ip_proxy_isolated": row[10],
            "last_active": row[11],
            "updated_at": row[12],
        }
    import json as _json

    projects_raw = d.get("assigned_projects") or "[]"
    try:
        projects = _json.loads(projects_raw) if isinstance(projects_raw, str) else list(projects_raw)
    except Exception:
        projects = []
    isolated = d.get("ip_proxy_isolated")
    return {
        "operator_id": d["operator_id"],
        "name": d["name"],
        "role": d["role"],
        "assigned_wallets": int(d.get("assigned_wallets") or 0),
        "assigned_projects": projects,
        "today_completed_tx": int(d.get("today_completed_tx") or 0),
        "today_target_tx": int(d.get("today_target_tx") or 0),
        "completion_rate": float(d.get("completion_rate") or 0.0),
        "gas_spent_usd": float(d.get("gas_spent_usd") or 0.0),
        "status": d.get("status") or "idle",
        "ip_proxy_isolated": None if isolated is None else bool(isolated),
        "last_active": d.get("last_active"),
    }


def _row_to_task(row: Any) -> dict[str, Any]:
    """容忍 dict / sqlite3.Row / tuple 三种行形态（与 faucet_registry 同款）。"""
    if hasattr(row, "keys") or isinstance(row, dict):
        d = dict(row)
    else:
        d = {
            "task_id": row[0],
            "title": row[1],
            "project": row[2],
            "operator_id": row[3],
            "target_wallet_count": row[4],
            "status": row[5],
            "priority": row[6],
            "deadline": row[7],
            "created_at": row[8],
        }
    return {
        "task_id": d["task_id"],
        "title": d["title"],
        "project": d["project"],
        "operator_id": d["operator_id"],
        "target_wallet_count": int(d.get("target_wallet_count") or 1),
        "status": d.get("status") or "pending",
        "priority": d.get("priority") or "medium",
        "deadline": d.get("deadline"),
        "created_at": int(d.get("created_at") or 0),
    }


def get_team_studio_dashboard(conn: DbConnection | None = None) -> dict[str, Any]:
    """获取工作室团队看板（空态诚实：无操作员时返回空列表而非演示数据）."""
    with connection_scope(conn) as c:
        ensure_team_studio_tables(c)
        ops_cursor = c.execute(
            f"SELECT {_OPERATOR_COLS} FROM {_OPERATORS_TABLE} ORDER BY updated_at ASC, operator_id ASC"  # noqa: S608 — 表名/列名均为内部字面量
        )
        operators = [_row_to_operator(r) for r in ops_cursor.fetchall()]
        tasks_cursor = c.execute(f"SELECT {_TASK_COLS} FROM {_TASKS_TABLE} ORDER BY created_at DESC, task_id ASC")  # noqa: S608 — 表名/列名均为内部字面量
        tasks = [_row_to_task(r) for r in tasks_cursor.fetchall()]

    total_wallets = sum(int(op["assigned_wallets"]) for op in operators)
    total_tx_today = sum(int(op["today_completed_tx"]) for op in operators)
    total_target_today = sum(int(op["today_target_tx"]) for op in operators)
    total_gas_usd = sum(float(op["gas_spent_usd"]) for op in operators)

    avg_completion = (total_tx_today / total_target_today) if total_target_today > 0 else 0.0

    return {
        "summary": {
            "team_name": "My Studio",
            "active_operators_count": len(operators),
            "total_managed_wallets": total_wallets,
            "today_total_transactions": total_tx_today,
            "overall_completion_rate": round(avg_completion, 2),
            "today_gas_budget_usd": round(total_gas_usd, 2),
            # 隔离评级需要真实操作/链上日志，无数据源前不输出（诚实空缺）
            "sybil_isolation_rating": None,
        },
        "operators": operators,
        "assigned_tasks": tasks,
        "persist_note": "数据已持久化到 SQLite，服务重启后保留；无真实操作/链上日志数据源。",
    }


def assign_task_to_operator(
    title: str,
    project: str,
    operator_id: str,
    target_wallet_count: int,
    priority: str = "medium",
    deadline: str = "今日 24:00",
    conn: DbConnection | None = None,
) -> dict[str, Any]:
    """为指定操作员派发新任务（操作员必须已注册）."""
    with connection_scope(conn) as c:
        ensure_team_studio_tables(c)
        op_cursor = c.execute(
            f"SELECT operator_id FROM {_OPERATORS_TABLE} WHERE operator_id = ?",  # noqa: S608 — 表名为内部字面量
            (operator_id,),
        )
        if op_cursor.fetchone() is None:
            return {"success": False, "error": f"操作员 {operator_id} 不存在，请先注册操作员"}

        new_task = {
            "task_id": f"task_{int(time.time() * 1000)}",
            "title": title.strip(),
            "project": project.strip(),
            "operator_id": operator_id.strip(),
            "target_wallet_count": max(1, target_wallet_count),
            "status": "pending",
            "priority": priority,
            "deadline": deadline,
            "created_at": int(time.time()),
        }
        c.execute(
            f"""
            INSERT INTO {_TASKS_TABLE}
                ({_TASK_COLS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,  # noqa: S608 — 表名/列名均为内部字面量，取值全部绑定
            (
                new_task["task_id"],
                new_task["title"],
                new_task["project"],
                new_task["operator_id"],
                new_task["target_wallet_count"],
                new_task["status"],
                new_task["priority"],
                new_task["deadline"],
                new_task["created_at"],
            ),
        )
        c.commit()
        return {"success": True, "task": new_task}


def register_or_update_operator(
    operator_id: str,
    name: str,
    role: str = "Operator",
    assigned_wallets: int = 10,
    assigned_projects: list[str] | None = None,
    conn: DbConnection | None = None,
) -> dict[str, Any]:
    """新增或更新操作员信息（新团队从零录入，无预置演示数据）."""
    import json as _json

    projects = assigned_projects or []
    with connection_scope(conn) as c:
        ensure_team_studio_tables(c)
        existing_cursor = c.execute(
            f"SELECT operator_id FROM {_OPERATORS_TABLE} WHERE operator_id = ?",  # noqa: S608 — 表名为内部字面量
            (operator_id,),
        )
        existing = existing_cursor.fetchone()
        projects_json = _json.dumps(projects, ensure_ascii=False)

        if existing:
            c.execute(
                f"""
                UPDATE {_OPERATORS_TABLE}
                SET name = ?, role = ?, assigned_wallets = ?, assigned_projects = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE operator_id = ?
                """,  # noqa: S608 — 表名/列名均为内部字面量，取值全部绑定
                (name, role, assigned_wallets, projects_json, operator_id),
            )
            c.commit()
            sel = c.execute(
                f"SELECT {_OPERATOR_COLS} FROM {_OPERATORS_TABLE} WHERE operator_id = ?",  # noqa: S608 — 表名/列名均为内部字面量
                (operator_id,),
            )
            row = sel.fetchone()
            return {"action": "updated", "operator": _row_to_operator(row) if row is not None else {}}

        now_text = "刚刚注册"
        c.execute(
            f"""
            INSERT INTO {_OPERATORS_TABLE}
                ({_OPERATOR_COLS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """,  # noqa: S608 — 表名/列名均为内部字面量，取值全部绑定
            (
                operator_id,
                name,
                role,
                assigned_wallets,
                projects_json,
                0,
                0,
                0.0,
                0.0,
                "idle",
                None,
                now_text,
            ),
        )
        c.commit()
        new_op = {
            "operator_id": operator_id,
            "name": name,
            "role": role,
            "assigned_wallets": assigned_wallets,
            "assigned_projects": projects,
            "today_completed_tx": 0,
            "today_target_tx": 0,
            "completion_rate": 0.0,
            "gas_spent_usd": 0.0,
            "status": "idle",
            "ip_proxy_isolated": None,
            "last_active": now_text,
        }
        return {"action": "created", "operator": new_op}
