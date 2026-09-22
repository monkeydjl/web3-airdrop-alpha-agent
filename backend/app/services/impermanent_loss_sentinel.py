"""AMM Impermanent Loss & Lending Liquidation Sentinel (无常损失与借贷清算预警服务).

为在 DeFi 空投（如 Scroll Ambient, Linea SyncSwap, Aave V3, Mendi Finance）提供 LP 或借贷质押的猎人提供：
1. AMM 恒定乘积与 Uniswap V3 集中流动性无常损失 (Impermanent Loss) 动态测算与手续费抵扣净损益；
2. 借贷协议健康因子 (Health Factor) 监控、极端行情以太坊清算临界价推演与紧急降杠杆避险预案。
"""

from __future__ import annotations

import math
from typing import Any
import structlog

logger = structlog.get_logger(__name__)


def calculate_amm_impermanent_loss(
    initial_deposit_usd: float = 5000.0,
    price_change_pct: float = 30.0,  # e.g. +30% or -30%
    is_concentrated_v3: bool = True,
    price_lower_bound_ratio: float = 0.8,  # 下限 80%
    price_upper_bound_ratio: float = 1.2,  # 上限 120%
    fee_apy_pct: float = 24.0,  # 年化手续费率
    holding_days: int = 30,
) -> dict[str, Any]:
    """测算 AMM 流动性池的无常损失与手续费抵扣后的实际盈亏."""
    deposit = max(1.0, float(initial_deposit_usd))
    k = max(0.01, 1.0 + (price_change_pct / 100.0))  # 价格变化倍数
    
    # 基础恒定乘积 IL = 2 * sqrt(k) / (1 + k) - 1
    base_il_ratio = (2.0 * math.sqrt(k)) / (1.0 + k) - 1.0
    base_il_pct = round(abs(base_il_ratio) * 100.0, 2)
    
    # 若为 Uni V3 集中流动性，无常损失会被杠杆区间放大
    if is_concentrated_v3 and price_upper_bound_ratio > price_lower_bound_ratio:
        # 集中倍数模拟
        range_span = price_upper_bound_ratio - price_lower_bound_ratio
        concentration_multiplier = min(5.0, max(1.2, 1.0 / range_span))
        effective_il_pct = round(min(100.0, base_il_pct * concentration_multiplier), 2)
    else:
        effective_il_pct = base_il_pct

    # 计算手续费收入
    earned_fee_usd = round(deposit * (fee_apy_pct / 100.0) * (holding_days / 365.0), 2)
    il_loss_usd = round(deposit * (effective_il_pct / 100.0), 2)
    net_pnl_usd = round(earned_fee_usd - il_loss_usd, 2)

    return {
        "initial_deposit_usd": deposit,
        "price_change_pct": price_change_pct,
        "is_concentrated_v3": is_concentrated_v3,
        "holding_days": holding_days,
        "impermanent_loss_pct": effective_il_pct,
        "impermanent_loss_usd": il_loss_usd,
        "earned_fee_usd": earned_fee_usd,
        "net_pnl_usd": net_pnl_usd,
        "is_profitable": net_pnl_usd >= 0,
        "risk_evaluation": (
            "手续费足以覆盖无常损失，LP 处于正收益状态"
            if net_pnl_usd >= 0
            else "币价单边脱离区间，无常损失超过手续费，建议及时单边撤出"
        ),
    }


def check_lending_health_factor(
    collateral_asset: str = "ETH",
    collateral_amount: float = 5.0,
    collateral_price_usd: float = 3200.0,
    liquidation_threshold: float = 0.825,  # 82.5% Aave ETH 标准
    borrowed_usd: float = 10000.0,
) -> dict[str, Any]:
    """监控借贷仓位健康因子 (Health Factor)，并推演以太坊清算价格底线."""
    total_collateral_usd = collateral_amount * collateral_price_usd
    borrow = max(1.0, float(borrowed_usd))
    
    # HF = (抵押物总值 * 清算阈值) / 借款额
    max_borrowable_at_liquidation = total_collateral_usd * liquidation_threshold
    health_factor = round(max_borrowable_at_liquidation / borrow, 2)
    
    # 清算价格: CollateralPrice_liq = Borrow / (CollateralAmount * LiquidationThreshold)
    liquidation_price = round(borrow / (collateral_amount * liquidation_threshold), 2)
    price_drop_to_liquidation_pct = round(
        ((collateral_price_usd - liquidation_price) / collateral_price_usd) * 100.0, 1
    )

    if health_factor >= 1.50:
        status = "SAFE"
        risk_color = "emerald"
        advice = "仓位极度安全，可抵御 40%+ 级极端下挫"
    elif health_factor >= 1.25:
        status = "MODERATE"
        risk_color = "amber"
        advice = "健康度一般，若市场暴跌超过 20% 需准备补仓"
    elif health_factor >= 1.05:
        status = "HIGH_RISK"
        risk_color = "orange"
        advice = "距离被清算仅一步之遥！建议立刻归还部分借款或补充抵押物"
    else:
        status = "CRITICAL_LIQUIDATION_IMMINENT"
        risk_color = "red"
        advice = "极度危险！随时可能被清算机器人吃掉清算罚金 (5%~10%)"

    return {
        "collateral_asset": collateral_asset,
        "collateral_value_usd": round(total_collateral_usd, 2),
        "borrowed_usd": round(borrow, 2),
        "health_factor": health_factor,
        "liquidation_price_usd": liquidation_price,
        "price_drop_to_liquidation_pct": max(0.0, price_drop_to_liquidation_pct),
        "status": status,
        "risk_color": risk_color,
        "action_advice": advice,
        "deleveraging_simulation": {
            "repay_usd_to_reach_1_8_hf": max(0.0, round(borrow - (max_borrowable_at_liquidation / 1.8), 2)),
            "add_eth_to_reach_1_8_hf": max(
                0.0,
                round(((borrow * 1.8) - max_borrowable_at_liquidation) / (collateral_price_usd * liquidation_threshold), 3),
            ),
        },
    }
