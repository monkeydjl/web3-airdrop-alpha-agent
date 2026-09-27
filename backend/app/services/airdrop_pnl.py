"""Airdrop PnL & Harvest Ledger Service (空投收益账本与历史战绩复盘服务).

记录与核算已落袋空投资产价值、扣除 Gas 摩擦成本，计算真实净利润 (Net PnL)、
投入产出比 (Gas RoI) 与猎人荣誉段位。

持久化（2026-09-23，docs/EXPANSION_AUDIT_REPORT.md P1）：账本此前是
`DEFAULT_HARVEST_RECORDS` 模块列表 + `add_harvest_record` 往里 insert——
用户手动录入的实收空投在服务重启后凭空蒸发，且「演示样例」与「用户数据」
混在同一张列表里无法区分。现沿用 faucet_claims 的同款模式落 SQLite
（``ensure_harvest_records_table`` + 可选 ``conn`` 注入）：

- 默认样例只在**首次建表**时播种一次（``is_default = 1``），此后以 DB 为准，
  用户可删除样例而不会被重启恢复；
- 用户录入 ``is_default = 0``，按 ``claimed_at`` 倒序 + 新插入在前展示。

诚实口径：内置样例仍是演示数据（行业公开战绩），响应体在路由层整体打
``data_quality: simulated`` 标记。
"""

import datetime
from typing import Any

import structlog

from app.db import DbConnection, connection_scope

logger = structlog.get_logger(__name__)

# 默认内置的历史空投战绩样例（行业公开战绩，仅首次建表播种；is_default=1 可删除）
DEFAULT_HARVEST_RECORDS: list[dict[str, Any]] = [
    {
        "id": "harvest-arb-001",
        "project_name": "Arbitrum",
        "token_symbol": "$ARB",
        "amount_claimed": 3250.0,
        "ath_price_usd": 2.25,
        "current_price_usd": 0.58,
        "gas_spent_usd": 48.5,
        "claimed_at": "2023-03-23",
        "notes": "交互 4 个生态 DApp，包含 Bridge 与 Uniswap LP",
    },
    {
        "id": "harvest-tia-002",
        "project_name": "Celestia",
        "token_symbol": "$TIA",
        "amount_claimed": 840.0,
        "ath_price_usd": 20.8,
        "current_price_usd": 5.4,
        "gas_spent_usd": 18.0,
        "claimed_at": "2023-10-31",
        "notes": "以太坊 L2 活跃地址零成本阳光普照",
    },
    {
        "id": "harvest-stark-003",
        "project_name": "Starknet",
        "token_symbol": "$STRK",
        "amount_claimed": 1100.0,
        "ath_price_usd": 3.65,
        "current_price_usd": 0.42,
        "gas_spent_usd": 85.0,
        "claimed_at": "2024-02-20",
        "notes": "连续 3 个月跨链交互与生态 Swap",
    },
    {
        "id": "harvest-zro-004",
        "project_name": "LayerZero",
        "token_symbol": "$ZRO",
        "amount_claimed": 520.0,
        "ath_price_usd": 5.1,
        "current_price_usd": 3.8,
        "gas_spent_usd": 120.0,
        "claimed_at": "2024-06-20",
        "notes": "跨 5 条链 Stargate 活跃转账，顺利通过女巫清洗",
    },
]

_HARVEST_TABLE = "harvest_records"

_HARVEST_COLS = (
    "id, project_name, token_symbol, amount_claimed, ath_price_usd, "
    "current_price_usd, gas_spent_usd, claimed_at, notes, is_default"
)


def ensure_harvest_records_table(conn: DbConnection) -> None:
    """Ensure the harvest_records table exists; seed default records once."""
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_HARVEST_TABLE} (
            id               TEXT PRIMARY KEY,
            project_name     TEXT NOT NULL,
            token_symbol     TEXT NOT NULL,
            amount_claimed   REAL NOT NULL,
            ath_price_usd    REAL NOT NULL,
            current_price_usd REAL NOT NULL,
            gas_spent_usd    REAL NOT NULL DEFAULT 0,
            claimed_at       TEXT,
            notes            TEXT,
            is_default       INTEGER NOT NULL DEFAULT 0,
            created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    conn.execute(f"CREATE INDEX IF NOT EXISTS idx_harvest_records_claimed ON {_HARVEST_TABLE}(claimed_at DESC);")
    seed_cursor = conn.execute(f"SELECT COUNT(*) FROM {_HARVEST_TABLE}")  # noqa: S608 — 表名为内部字面量
    seed_count = _first_int(seed_cursor.fetchone())
    if seed_count == 0:
        for rec in DEFAULT_HARVEST_RECORDS:
            conn.execute(
                f"""
                INSERT INTO {_HARVEST_TABLE}
                    ({_HARVEST_COLS})
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,  # noqa: S608 — 表名/列名均为内部字面量，取值全部绑定
                (
                    rec["id"],
                    rec["project_name"],
                    rec["token_symbol"],
                    float(rec["amount_claimed"]),
                    float(rec["ath_price_usd"]),
                    float(rec["current_price_usd"]),
                    float(rec["gas_spent_usd"]),
                    rec["claimed_at"],
                    rec["notes"],
                    1,
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


def _row_to_record(row: Any) -> dict[str, Any]:
    """容忍 dict / sqlite3.Row / tuple 三种行形态（与 faucet_registry 同款）。"""
    if hasattr(row, "keys") or isinstance(row, dict):
        d = dict(row)
    else:
        d = {
            "id": row[0],
            "project_name": row[1],
            "token_symbol": row[2],
            "amount_claimed": row[3],
            "ath_price_usd": row[4],
            "current_price_usd": row[5],
            "gas_spent_usd": row[6],
            "claimed_at": row[7],
            "notes": row[8],
            "is_default": row[9],
        }
    rec = dict(d)
    rec.pop("is_default", None)
    rec.pop("created_at", None)
    for k in ("amount_claimed", "ath_price_usd", "current_price_usd", "gas_spent_usd"):
        rec[k] = float(rec.get(k) or 0.0)
    return rec


def get_pnl_summary(conn: DbConnection | None = None) -> dict[str, Any]:
    """汇总计算空投收益、投入成本与战绩评级."""
    with connection_scope(conn) as c:
        ensure_harvest_records_table(c)
        cursor = c.execute(
            f"SELECT {_HARVEST_COLS} FROM {_HARVEST_TABLE} ORDER BY claimed_at DESC, created_at DESC, id ASC"  # noqa: S608 — 表名/列名均为内部字面量
        )
        records = [_row_to_record(r) for r in cursor.fetchall()]

    total_realized_current_usd = 0.0
    total_realized_ath_usd = 0.0
    total_gas_spent_usd = 0.0

    enhanced_records = []
    for r in records:
        curr_val = r["amount_claimed"] * r["current_price_usd"]
        ath_val = r["amount_claimed"] * r["ath_price_usd"]
        gas = r["gas_spent_usd"]
        net_profit = curr_val - gas
        roi_multiple = round(curr_val / (gas or 1.0), 1)

        total_realized_current_usd += curr_val
        total_realized_ath_usd += ath_val
        total_gas_spent_usd += gas

        rec = dict(r)
        rec["current_value_usd"] = round(curr_val, 2)
        rec["ath_value_usd"] = round(ath_val, 2)
        rec["net_profit_usd"] = round(net_profit, 2)
        rec["gas_roi_multiple"] = roi_multiple
        enhanced_records.append(rec)

    net_current_profit = total_realized_current_usd - total_gas_spent_usd
    overall_roi = (
        round(total_realized_current_usd / (total_gas_spent_usd or 1.0), 1) if total_gas_spent_usd > 0 else 0.0
    )

    # 猎人荣誉段位判定
    if total_realized_ath_usd >= 50000:
        tier = "S-Tier Hunter King (传奇猎皇)"
        tier_badge = "👑 传奇猎皇"
    elif total_realized_ath_usd >= 10000:
        tier = "Diamond Vanguard (钻石先锋)"
        tier_badge = "💎 钻石先锋"
    elif total_realized_ath_usd >= 3000:
        tier = "Gold Pioneer (黄金主力)"
        tier_badge = "🥇 黄金主力"
    else:
        tier = "Silver Explorer (白银探索者)"
        tier_badge = "🥈 白银探索者"

    return {
        "ok": True,
        "total_claimed_projects": len(enhanced_records),
        "total_current_value_usd": round(total_realized_current_usd, 2),
        "total_ath_value_usd": round(total_realized_ath_usd, 2),
        "total_gas_spent_usd": round(total_gas_spent_usd, 2),
        "net_current_profit_usd": round(net_current_profit, 2),
        "overall_roi_multiple": overall_roi,
        "hunter_tier": tier,
        "hunter_tier_badge": tier_badge,
        "records": enhanced_records,
    }


def add_harvest_record(record_data: dict[str, Any], conn: DbConnection | None = None) -> dict[str, Any]:
    """新增一条已落袋空投记账（持久化，重启不再丢失）."""
    with connection_scope(conn) as c:
        ensure_harvest_records_table(c)
        now_iso = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        new_record = {
            "id": f"harvest-custom-{int(datetime.datetime.now().timestamp() * 1000)}",
            "project_name": record_data.get("project_name", "自定义空投项目"),
            "token_symbol": record_data.get("token_symbol", "$TOKEN"),
            "amount_claimed": float(record_data.get("amount_claimed") or 0.0),
            "ath_price_usd": float(record_data.get("ath_price_usd") or 1.0),
            "current_price_usd": float(record_data.get("current_price_usd") or 1.0),
            "gas_spent_usd": float(record_data.get("gas_spent_usd") or 0.0),
            "claimed_at": record_data.get("claimed_at") or now_iso,
            "notes": record_data.get("notes", "手动录入实收空投"),
        }
        c.execute(
            f"""
            INSERT INTO {_HARVEST_TABLE}
                ({_HARVEST_COLS})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,  # noqa: S608 — 表名/列名均为内部字面量，取值全部绑定
            (
                new_record["id"],
                new_record["project_name"],
                new_record["token_symbol"],
                new_record["amount_claimed"],
                new_record["ath_price_usd"],
                new_record["current_price_usd"],
                new_record["gas_spent_usd"],
                new_record["claimed_at"],
                new_record["notes"],
                0,
            ),
        )
        c.commit()
        return {"ok": True, "data": new_record}
