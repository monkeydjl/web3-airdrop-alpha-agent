"""Airdrop Epoch Points & Snapshot Progress Estimator (空投阶段积分估值与快照倍数推演器).

建立主流积分制协议（Scroll, Linea, Hyperliquid, Symbiotic, Karak）积分池分布与代币折算模型，
推演全网排位、代币预估回报与冲刺下一梯队的加权加速方案。
"""

from __future__ import annotations

from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 预设各大知名积分协议数据模型
_PROTOCOLS: dict[str, dict[str, Any]] = {
    "scroll_marks": {
        "id": "scroll_marks",
        "name": "Scroll Marks (Session 2)",
        "token_symbol": "SCR",
        "total_points_supply": 320_000_000,
        "airdrop_pool_tokens": 70_000_000,
        "estimated_token_price_usd": 1.15,
        "tier_thresholds": {
            "whale": 100_000,
            "pioneer": 25_000,
            "active": 5_000,
        },
        "boost_strategies": [
            {"pool": "Puffer / Kelp Restaking", "multiplier": "3.0x", "desc": "在 Scroll 主网存入流动性再质押资产"},
            {"pool": "Ambient DEX LP 深度做市", "multiplier": "2.5x", "desc": "提供 ETH/USDC 集中流动性"},
            {"pool": "Scroll Canvas 链上徽章收集", "multiplier": "+20% 全局加成", "desc": "铸造生态专属荣誉徽章"},
        ],
    },
    "linea_voyage": {
        "id": "linea_voyage",
        "name": "Linea Voyage / LXP Points",
        "token_symbol": "LINEA",
        "total_points_supply": 2_100_000_000,
        "airdrop_pool_tokens": 160_000_000,
        "estimated_token_price_usd": 0.85,
        "tier_thresholds": {
            "whale": 500_000,
            "pioneer": 100_000,
            "active": 20_000,
        },
        "boost_strategies": [
            {"pool": "Proof of Humanity (PoH) 认证", "multiplier": "核心门槛", "desc": "完成人脸/生物实人认证解锁空投资格"},
            {"pool": "SyncSwap / Velocore 交易流动性", "multiplier": "2.0x", "desc": "原生 DEX 提供稳定币对"},
            {"pool": "Lendle / ZeroLend 借贷存款", "multiplier": "1.8x", "desc": "借贷协议供应资产"},
        ],
    },
    "hyperliquid_points": {
        "id": "hyperliquid_points",
        "name": "Hyperliquid Points",
        "token_symbol": "HYPE",
        "total_points_supply": 60_000_000,
        "airdrop_pool_tokens": 310_000_000,
        "estimated_token_price_usd": 8.50,
        "tier_thresholds": {
            "whale": 20_000,
            "pioneer": 4_000,
            "active": 800,
        },
        "boost_strategies": [
            {"pool": "Perps Taker 合约主动交易量", "multiplier": "2.5x", "desc": "每周交易量超过 $50,000 积分加速"},
            {"pool": "HLP 流动性金库金银池", "multiplier": "1.8x", "desc": "为做市协议金库提供 USDC 承兑"},
            {"pool": "现货交易挂单 Maker 深度", "multiplier": "1.5x", "desc": "挂单提供现货盘口深度"},
        ],
    },
    "symbiotic_points": {
        "id": "symbiotic_points",
        "name": "Symbiotic Restaking Points",
        "token_symbol": "SYM",
        "total_points_supply": 950_000_000,
        "airdrop_pool_tokens": 65_000_000,
        "estimated_token_price_usd": 2.60,
        "tier_thresholds": {
            "whale": 250_000,
            "pioneer": 50_000,
            "active": 10_000,
        },
        "boost_strategies": [
            {"pool": "Mellow Protocol 组合金库", "multiplier": "2.5x", "desc": "存入专属定制再质押策略金库"},
            {"pool": "Ethena USDe 稳定币网络质押", "multiplier": "2.0x", "desc": "参与合成美元共识安全性担保"},
            {"pool": "Lido wstETH 原生网络质押", "multiplier": "1.2x", "desc": "稳健低风险以太坊质押"},
        ],
    },
    "karak_xp": {
        "id": "karak_xp",
        "name": "Karak Network XP",
        "token_symbol": "KARAK",
        "total_points_supply": 1_400_000_000,
        "airdrop_pool_tokens": 85_000_000,
        "estimated_token_price_usd": 1.75,
        "tier_thresholds": {
            "whale": 300_000,
            "pioneer": 60_000,
            "active": 15_000,
        },
        "boost_strategies": [
            {"pool": "全链跨资产万物再质押", "multiplier": "2.0x", "desc": "在 Arbitrum/Optimism 多链存入非 ETH 资产"},
            {"pool": "早期先行者 Pioneer 创世加成", "multiplier": "1.5x", "desc": "持续质押超过 60 天获得时间乘数"},
        ],
    },
}


def get_supported_protocols() -> list[dict[str, Any]]:
    """返回所有支持积分测算的协议列表与基本模型参数."""
    return [
        {
            "id": p["id"],
            "name": p["name"],
            "token_symbol": p["token_symbol"],
            "total_points_supply": p["total_points_supply"],
            "airdrop_pool_tokens": p["airdrop_pool_tokens"],
            "estimated_token_price_usd": p["estimated_token_price_usd"],
        }
        for p in _PROTOCOLS.values()
    ]


def estimate_points_airdrop(
    protocol_id: str,
    user_points: float,
    capital_invested_usd: float = 0.0,
    days_active: int = 30,
) -> dict[str, Any]:
    """计算用户积分在对应协议中的全网排位、代币折算值与冲刺优化建议."""
    pid = protocol_id.lower().strip()
    proto = _PROTOCOLS.get(pid, _PROTOCOLS["scroll_marks"])

    pts = max(0.0, float(user_points))
    cap = max(0.0, float(capital_invested_usd))
    total_supply = float(proto["total_points_supply"])
    pool_tokens = float(proto["airdrop_pool_tokens"])
    price = float(proto["estimated_token_price_usd"])

    # 1. 计算占全网积分池比重
    share_pct = round((pts / max(1.0, total_supply)) * 100, 6)

    # 2. 折算代币数与 USD 总价值
    estimated_tokens = round((pts / max(1.0, total_supply)) * pool_tokens, 2)
    estimated_usd = round(estimated_tokens * price, 2)

    # 3. 投入产出比与资本年化 (APR / RoI)
    roi_multiple = round(estimated_usd / max(1.0, cap), 2) if cap > 0 else 0.0

    # 4. 全网排位与段位判定
    thresh = proto["tier_thresholds"]
    if pts >= thresh["whale"]:
        tier = "whale"
        tier_label = "🏆 巨鲸头部梯队 (Top 0.5%)"
        percentile_text = "前 0.5% 核心权重"
        next_target = None
        sprint_advice = "您已位居该协议全网顶级巨鲸阵营，建议保持当前仓位，防止质押资金提前撤出导致快照时排名下滑。"
    elif pts >= thresh["pioneer"]:
        tier = "pioneer"
        tier_label = "⭐ 先锋主力梯队 (Top 5%)"
        percentile_text = "前 5% 主力猎人"
        next_target = thresh["whale"] - pts
        sprint_advice = f"距离冲刺「巨鲸头部梯队」还需约 {int(next_target):,} 积分，建议配置下方加权加速池提升每日积分产出。"
    elif pts >= thresh["active"]:
        tier = "active"
        tier_label = "🎯 活跃中坚梯队 (Top 20%)"
        percentile_text = "前 20% 活跃用户"
        next_target = thresh["pioneer"] - pts
        sprint_advice = f"距离冲刺「先锋主力梯队」还需约 {int(next_target):,} 积分，建议尽早切换至高倍数加速金库。"
    else:
        tier = "dust"
        tier_label = "🌱 基础低保梯队 (Top 50%)"
        percentile_text = "前 50% 基础参与"
        next_target = thresh["active"] - pts
        sprint_advice = f"当前积分处于低保边缘，建议至少补足 {int(next_target):,} 积分进入活跃中坚档，避免触碰快照最低空投门槛。"

    return {
        "ok": True,
        "protocol": {
            "id": proto["id"],
            "name": proto["name"],
            "token_symbol": proto["token_symbol"],
            "estimated_token_price_usd": price,
            "airdrop_pool_tokens": pool_tokens,
            "total_points_supply": total_supply,
        },
        "user_input": {
            "user_points": pts,
            "capital_invested_usd": cap,
            "days_active": days_active,
        },
        "valuation": {
            "share_of_pool_pct": share_pct,
            "estimated_tokens": estimated_tokens,
            "estimated_usd_value": estimated_usd,
            "roi_multiple": roi_multiple,
            "tier": tier,
            "tier_label": tier_label,
            "percentile_text": percentile_text,
            "next_tier_target_points": next_target,
        },
        "sprint_advice": sprint_advice,
        "boost_strategies": proto["boost_strategies"],
    }
