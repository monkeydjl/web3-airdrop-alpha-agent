"""Gas Alert Engine (全链 Gas 异动智能预警与阈值规则引擎).

允许空投猎人配置链上 Gas 阈值规则（极低交互窗口 / 拥堵防夹警报），动态扫描并输出即时告警。

持久化（2026-09-23，docs/EXPANSION_AUDIT_REPORT.md P1）：规则此前存模块级内存，
重启即失——用户配好的「以太坊低于 12 Gwei 提醒我」在服务重启后悄悄消失。
现沿用 faucet_claims 的同款模式落 SQLite（``ensure_gas_alert_rules_table`` +
可选 ``conn`` 注入），函数签名与返回形态保持兼容。评估函数 ``evaluate_active_alerts``
只读规则，同样走 DB。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from app.db import DbConnection, connection_scope
from app.services.gas_tracker import get_all_chains_gas_summary

logger = structlog.get_logger(__name__)

# 预设推荐规则（首次建表时播种一次，之后以 DB 内容为准）
DEFAULT_RULES: list[dict[str, Any]] = [
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

_RULES_TABLE = "gas_alert_rules"


def ensure_gas_alert_rules_table(conn: DbConnection) -> None:
    """Ensure the gas_alert_rules table and indexes exist; seed defaults once."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_RULES_TABLE} (
            rule_id        TEXT PRIMARY KEY,
            chain          TEXT NOT NULL,
            condition      TEXT NOT NULL,
            threshold_gwei REAL NOT NULL,
            label          TEXT NOT NULL,
            enabled        INTEGER NOT NULL DEFAULT 1,
            created_at     TIMESTAMP
        );
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_gas_alert_rules_chain ON {_RULES_TABLE}(chain, enabled);")
    seed_cursor = conn.execute(f"SELECT COUNT(*) FROM {_RULES_TABLE}")  # noqa: S608 — 表名为内部字面量
    seed_count = _first_int(seed_cursor.fetchone())
    if seed_count == 0:
        for rule in DEFAULT_RULES:
            conn.execute(
                f"""
                INSERT INTO {_RULES_TABLE}
                    (rule_id, chain, condition, threshold_gwei, label, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: S608 — 表名为内部字面量，取值全部绑定
                (
                    rule["id"],
                    rule["chain"],
                    rule["condition"],
                    float(rule["threshold_gwei"]),
                    rule["label"],
                    1 if rule["enabled"] else 0,
                    rule["created_at"],
                ),
            )
    conn.commit()


def _first_int(row: Any) -> int:
    """取单列查询首列的 int 值（容忍 dict / sqlite3.Row / tuple 行形态）。"""
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(next(iter(row.values()), 0) or 0)
    return int(row[0] or 0)


def _row_to_rule(row: Any) -> dict[str, Any]:
    """容忍 dict / sqlite3.Row / tuple 三种行形态（与 faucet_registry 同款）。"""
    if hasattr(row, "keys") or isinstance(row, dict):
        d = dict(row)
    else:
        d = {
            "rule_id": row[0],
            "chain": row[1],
            "condition": row[2],
            "threshold_gwei": row[3],
            "label": row[4],
            "enabled": row[5],
            "created_at": row[6],
        }
    return {
        "id": d["rule_id"],
        "chain": d["chain"],
        "condition": d["condition"],
        "threshold_gwei": float(d["threshold_gwei"]),
        "label": d["label"],
        "enabled": bool(d["enabled"]),
        "created_at": d["created_at"],
    }


def get_all_rules(conn: DbConnection | None = None) -> list[dict[str, Any]]:
    """获取所有已配置的 Gas 告警规则."""
    with connection_scope(conn) as c:
        ensure_gas_alert_rules_table(c)
        cursor = c.execute(
            f"SELECT rule_id, chain, condition, threshold_gwei, label, enabled, created_at"  # noqa: S608 — 表名为内部字面量
            f" FROM {_RULES_TABLE} ORDER BY created_at ASC, rule_id ASC"
        )
        return [_row_to_rule(r) for r in cursor.fetchall()]


def create_rule(
    chain: str,
    condition: Literal["below", "above"],
    threshold_gwei: float,
    label: str,
    enabled: bool = True,
    conn: DbConnection | None = None,
) -> dict[str, Any]:
    """创建一条新的 Gas 阈值告警规则."""
    with connection_scope(conn) as c:
        ensure_gas_alert_rules_table(c)
        rule_id = f"rule-{chain.lower().strip()}-{uuid.uuid4().hex[:6]}"
        created_at = datetime.now(UTC).isoformat()
        c.execute(
            f"""
            INSERT INTO {_RULES_TABLE}
                (rule_id, chain, condition, threshold_gwei, label, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,  # noqa: S608 — 表名为内部字面量，取值全部绑定,
            (
                rule_id,
                chain.lower().strip(),
                condition,
                float(threshold_gwei),
                label.strip() or f"{chain.upper()} Gas {condition} {threshold_gwei} Gwei",
                1 if enabled else 0,
                created_at,
            ),
        )
        c.commit()
        return {
            "id": rule_id,
            "chain": chain.lower().strip(),
            "condition": condition,
            "threshold_gwei": float(threshold_gwei),
            "label": label.strip() or f"{chain.upper()} Gas {condition} {threshold_gwei} Gwei",
            "enabled": enabled,
            "created_at": created_at,
        }


def delete_rule(rule_id: str, conn: DbConnection | None = None) -> bool:
    """根据 ID 删除告警规则."""
    with connection_scope(conn) as c:
        ensure_gas_alert_rules_table(c)
        cursor = c.execute(f"DELETE FROM {_RULES_TABLE} WHERE rule_id = ?", (rule_id,))  # noqa: S608 — 表名为内部字面量
        c.commit()
        # sqlite3.Cursor.rowcount 对 DELETE 返回受影响行数；PG cursor 同样支持
        rowcount = getattr(cursor, "rowcount", 0) or 0
        return int(rowcount) > 0


def toggle_rule(
    rule_id: str,
    enabled: bool,
    conn: DbConnection | None = None,
) -> dict[str, Any] | None:
    """切换告警规则启用状态."""
    with connection_scope(conn) as c:
        ensure_gas_alert_rules_table(c)
        cursor = c.execute(
            f"UPDATE {_RULES_TABLE} SET enabled = ? WHERE rule_id = ?",  # noqa: S608 — 表名为内部字面量
            (1 if enabled else 0, rule_id),
        )
        c.commit()
        if int(getattr(cursor, "rowcount", 0) or 0) <= 0:
            return None
        sel = c.execute(
            f"SELECT rule_id, chain, condition, threshold_gwei, label, enabled, created_at"  # noqa: S608 — 表名为内部字面量
            f" FROM {_RULES_TABLE} WHERE rule_id = ?",
            (rule_id,),
        )
        row = sel.fetchone()
        return _row_to_rule(row) if row is not None else None


def reset_rules_to_default(conn: DbConnection | None = None) -> None:
    """重置为默认规则集（清空后由 ensure 的 seed 逻辑重新播种）."""
    with connection_scope(conn) as c:
        ensure_gas_alert_rules_table(c)
        c.execute(f"DELETE FROM {_RULES_TABLE}")  # noqa: S608 — 表名为内部字面量
        c.commit()
        ensure_gas_alert_rules_table(c)


def evaluate_active_alerts(
    custom_gas_summary: dict[str, Any] | None = None,
    conn: DbConnection | None = None,
) -> list[dict[str, Any]]:
    """比对当前实时 Gas 与已启用的规则，输出触发中的告警列表.

    custom_gas_summary 是 `get_all_chains_gas_summary()` 的返回形态：
    `{"chains": {chain: {"gwei": ...}}}`。此处曾读 `summary["data"][chain]["gas_gwei"]`，
    与真实形态完全断裂，生产端点 `/gas/alerts/active` 永远返回空列表；
    旧测试用 mock 喂了同款错误形态，才把 bug 钉成了「预期行为」。
    """
    gas_summary = custom_gas_summary or get_all_chains_gas_summary()
    chains_data = gas_summary.get("chains") or {}

    active_alerts: list[dict[str, Any]] = []

    for rule in get_all_rules(conn=conn):
        if not rule.get("enabled", True):
            continue

        chain = rule["chain"]
        chain_info = chains_data.get(chain)
        if not chain_info:
            continue

        current_gwei = float(chain_info.get("gwei", 0.0))
        condition = rule["condition"]
        threshold = rule["threshold_gwei"]
        is_triggered = False

        if (condition == "below" and current_gwei <= threshold) or (condition == "above" and current_gwei >= threshold):
            is_triggered = True

        if is_triggered:
            severity = "success" if condition == "below" else "warning"
            action = "适合进行高价值链上交互与批量转账" if condition == "below" else "建议暂时避开或调低滑点"
            message = (
                f"⚡ [{chain.upper()}] 当前实时 Gas 仅 {current_gwei} Gwei (低于阈值 {threshold} Gwei)，{action}！"
                if condition == "below"
                else f"🚨 [{chain.upper()}] 当前实时 Gas 达到 {current_gwei} Gwei "
                f"(超出设定阈值 {threshold} Gwei)，{action}！"
            )

            active_alerts.append(
                {
                    "rule_id": rule["id"],
                    "label": rule["label"],
                    "chain": chain,
                    "current_gwei": current_gwei,
                    "threshold_gwei": threshold,
                    "condition": condition,
                    "severity": severity,
                    "message": message,
                    "triggered_at": datetime.now(UTC).isoformat(),
                }
            )

    return active_alerts
