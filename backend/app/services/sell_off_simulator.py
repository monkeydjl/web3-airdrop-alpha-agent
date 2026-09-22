"""Airdrop Sell-Off Simulator (空投领取代币出局与止盈策略模拟器).

基于历史各大代币 TGE 后期走势规律，为猎人模拟并对比 4 大经典出局策略的期望收益与风险分布。
"""

from __future__ import annotations

from typing import Any, Literal
import structlog

logger = structlog.get_logger(__name__)

# 不同赛道代币在 TGE 后 30-90 天的历史平均价格漂移系数模型
_SECTOR_DRIFT = {
    "layer2": {
        "30d_price_factor": 0.82,     # L2 代币普遍存在流通抛压，首月平均 -18%
        "moonbag_1y_factor": 0.95,
        "staking_apr": 0.08,
        "ecosystem_airdrop_bonus": 0.12,
        "recommendation": "dca_30d",
        "rationale": "Layer-2 生态代币在首周热度过去后通常经历释放沉淀期，建议采用 30 天梯级 DCA 止盈或开盘秒砸锁定利润。"
    },
    "infrastructure": {
        "30d_price_factor": 1.15,     # 模块化/底层基础设施首月常有强共识溢价
        "moonbag_1y_factor": 1.40,
        "staking_apr": 0.16,
        "ecosystem_airdrop_bonus": 0.35,  # 质押生态子项目空投丰厚 (如 TIA/ATOM 质押者)
        "recommendation": "moonbag_50_50",
        "rationale": "头部基础设施项目往往作为质押资产享受后续众多生态子项目空投加成，推荐 50% 保本出金 + 50% 质押零成本长持。"
    },
    "defi": {
        "30d_price_factor": 0.88,
        "moonbag_1y_factor": 0.90,
        "staking_apr": 0.22,          # DeFi 协议自身 LP/质押收益较高
        "ecosystem_airdrop_bonus": 0.10,
        "recommendation": "dca_30d",
        "rationale": "DeFi 代币受流动性挖矿稀释影响明显，建议开盘卖出部分覆盖成本，剩余分批止盈。"
    },
    "ai": {
        "30d_price_factor": 1.10,
        "moonbag_1y_factor": 1.30,
        "staking_apr": 0.12,
        "ecosystem_airdrop_bonus": 0.20,
        "recommendation": "moonbag_50_50",
        "rationale": "AI 与 DePIN 赛道叙事弹性高，容易受宏观科技热度催化，保留底仓能捕捉超额爆发收益。"
    },
    "other": {
        "30d_price_factor": 0.85,
        "moonbag_1y_factor": 0.85,
        "staking_apr": 0.10,
        "ecosystem_airdrop_bonus": 0.15,
        "recommendation": "instant_dump",
        "rationale": "常规项目缺乏长期锁仓质押飞轮，开盘快速出清 (Instant Dump) 能够以最低风险获取确定性利润并投入下一个标的。"
    }
}


def simulate_sell_off_strategies(
    token_amount: float,
    initial_price_usd: float,
    sector: str = "layer2",
    persona: Literal["conservative", "balanced", "aggressive", "farmer_whale"] = "balanced",
) -> dict[str, Any]:
    """计算 4 种止盈出局策略的收益模拟与裁决推荐."""
    amt = max(0.0, float(token_amount))
    price = max(0.0001, float(initial_price_usd))
    initial_gross_value = round(amt * price, 2)

    sec_key = sector.lower().strip()
    config = _SECTOR_DRIFT.get(sec_key, _SECTOR_DRIFT["other"])

    # 1. 开盘秒砸 (Instant Dump)
    # 首日通常有 5% 的抢跑滑点磨损
    instant_exec_price = price * 0.95
    instant_return = round(amt * instant_exec_price, 2)
    strat_instant = {
        "strategy_id": "instant_dump",
        "name": "开盘秒砸 / 首日全额出清",
        "tag": "确定性落袋",
        "expected_return_usd": instant_return,
        "immediate_cash_usd": instant_return,
        "risk_level": "low",
        "risk_score": 10,
        "suitability": "适合风险厌恶者、工作室批量多号归集或高流通抛压项目",
        "pros": ["100% 利润落袋为安，零踏空回撤风险", "无摩擦即刻释放资金进入下一轮挖矿", "规避早期做市商控盘砸盘"],
        "cons": ["若遇到单边暴涨牛市可能错失后续数倍涨幅 (如早期 TIA / SUI)"]
    }

    # 2. 30天梯级 DCA 分批止盈 (Laddered DCA)
    # 假设均价受赛道 30 天漂移影响
    avg_dca_price = price * (1.0 + (config["30d_price_factor"] - 1.0) * 0.5)
    dca_return = round(amt * avg_dca_price, 2)
    strat_dca = {
        "strategy_id": "dca_30d",
        "name": "30天梯级分批止盈 (Laddered DCA)",
        "tag": "平滑波动",
        "expected_return_usd": dca_return,
        "immediate_cash_usd": round(dca_return * 0.25, 2),
        "risk_level": "medium",
        "risk_score": 45,
        "suitability": "适合主流 L2、主网级成熟生态或中等风险偏好的资深猎人",
        "pros": ["避免极端开盘低点被洗出", "分 4 周阶梯出金，兼顾现金流与反弹红利", "操作纪律严明"],
        "cons": ["需要持续跟踪行情与支付多笔链上 Swap Gas 费用"]
    }

    # 3. 保本出金 50% + 底仓长持 (Moonbag 50/50)
    cash_part = round((amt * 0.5) * instant_exec_price, 2)
    moonbag_expected = round((amt * 0.5) * (price * config["moonbag_1y_factor"]), 2)
    moonbag_total = round(cash_part + moonbag_expected, 2)
    strat_moonbag = {
        "strategy_id": "moonbag_50_50",
        "name": "50% 快速保本 + 50% 免费底仓 (Moonbag)",
        "tag": "零心理压力",
        "expected_return_usd": moonbag_total,
        "immediate_cash_usd": cash_part,
        "risk_level": "medium",
        "risk_score": 50,
        "suitability": "适合高估值创新公链、模块化基建或 AI 爆发型叙事",
        "pros": ["首日收回全部交互成本与利润，处于绝对不败之地", "剩余 50% 筹码作为零成本彩票无惧短期暴跌", "享受项目 1 年内爆发的超级红利"],
        "cons": ["若项目长期破发，剩余 50% 底仓价值将大幅缩水"]
    }

    # 4. 全额质押生息博二期空投 (Staking & Ecosystem Phase 2)
    # 100% 质押 1 年，获得质押 APR + 生态空投空投包
    staking_total_factor = config["moonbag_1y_factor"] * (1.0 + config["staking_apr"] + config["ecosystem_airdrop_bonus"])
    staking_return = round(amt * price * staking_total_factor, 2)
    strat_staking = {
        "strategy_id": "staking_yield",
        "name": "全额生态质押博二期空投 (Restaking & Phase 2)",
        "tag": "生态复利",
        "expected_return_usd": staking_return,
        "immediate_cash_usd": 0.0,
        "risk_level": "high",
        "risk_score": 80,
        "suitability": "适合大资金巨鲸、坚定看好生态基础设施的大户",
        "pros": ["享受官方验证节点质押年化收益 (APR 8%~22%)", "具备高概率获取生态后续发射新项目的创世空投资格", "免去频繁盯盘烦恼"],
        "cons": ["代币锁仓流动性锁定，代币价格单边下跌时无法及时止损"]
    }

    strategies = [strat_instant, strat_dca, strat_moonbag, strat_staking]

    # 根据用户风险偏好与赛道，智能推选最优策略
    recommended_id = config["recommendation"]
    if persona == "conservative":
        recommended_id = "instant_dump"
    elif persona == "aggressive":
        recommended_id = "moonbag_50_50" if sec_key != "infrastructure" else "staking_yield"
    elif persona == "farmer_whale":
        recommended_id = "staking_yield" if sec_key in ["infrastructure", "layer2"] else "instant_dump"

    rationale = config["rationale"]
    if persona == "conservative":
        rationale = "根据您的稳健防御型角色，锁定现金利润落袋为安是第一准则，推荐采用开盘秒砸策略。"

    return {
        "ok": True,
        "input_summary": {
            "token_amount": amt,
            "initial_price_usd": price,
            "initial_gross_value_usd": initial_gross_value,
            "sector": sec_key,
            "persona": persona,
        },
        "strategies": strategies,
        "recommended_strategy": recommended_id,
        "recommendation_rationale": rationale,
    }
