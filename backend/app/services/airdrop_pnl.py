"""Airdrop PnL & Harvest Ledger Service (空投收益账本与历史战绩复盘服务).

记录与核算已落袋空投资产价值、扣除 Gas 摩擦成本，计算真实净利润 (Net PnL)、
投入产出比 (Gas RoI) 与猎人荣誉段位。
"""

import datetime
from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 默认内置的历史空投战绩样例（提供开箱即用行业基准复盘）
DEFAULT_HARVEST_RECORDS = [
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


def get_pnl_summary() -> dict[str, Any]:
    """汇总计算空投收益、投入成本与战绩评级."""
    records = list(DEFAULT_HARVEST_RECORDS)

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
        round(total_realized_current_usd / (total_gas_spent_usd or 1.0), 1)
        if total_gas_spent_usd > 0
        else 0.0
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


def add_harvest_record(record_data: dict[str, Any]) -> dict[str, Any]:
    """新增一条已落袋空投记账."""
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    new_record = {
        "id": f"harvest-custom-{int(datetime.datetime.now().timestamp())}",
        "project_name": record_data.get("project_name", "自定义空投项目"),
        "token_symbol": record_data.get("token_symbol", "$TOKEN"),
        "amount_claimed": float(record_data.get("amount_claimed") or 0.0),
        "ath_price_usd": float(record_data.get("ath_price_usd") or 1.0),
        "current_price_usd": float(record_data.get("current_price_usd") or 1.0),
        "gas_spent_usd": float(record_data.get("gas_spent_usd") or 0.0),
        "claimed_at": record_data.get("claimed_at") or now_iso,
        "notes": record_data.get("notes", "手动录入实收空投"),
    }
    DEFAULT_HARVEST_RECORDS.insert(0, new_record)
    return {"ok": True, "data": new_record}
