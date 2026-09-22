"""Whale Mirror Airdrop Trajectory Backtester (顶级空投巨鲸链上轨迹镜像与快照反推服务).

逆向复盘历史顶级空投（Arbitrum, LayerZero, ZKsync, Starknet）Top 1% 获利胜者（>$50,000 代币）在快照前的关键指标：
- 活跃自然月跨度 (Active Months)
- 交互总笔数 (Total Tx Count)
- 独立智能合约数量 (Distinct Contracts)
- 累计跨链资金体量 (Bridged Volume USD)
- 快照日留存代币余额 (Snapshot Retained Balance)
并对齐映射至 Monad, Berachain, Story Protocol 等即将发币项目，生成战神作业镜像清单。
"""

from __future__ import annotations

from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 历史顶级大毛获利战神基准模型 (Top 1% 获得最高档位代币)
HISTORICAL_WHALE_BENCHMARKS: list[dict[str, Any]] = [
    {
        "airdrop_id": "arbitrum_top_tier",
        "name": "Arbitrum ($ARB) 顶级空投战神",
        "top_reward_tokens": "10,250 ARB (~$14,000)",
        "active_months_required": 9,
        "total_txs_required": 65,
        "distinct_contracts_required": 32,
        "bridged_volume_usd_required": 10000.0,
        "retained_balance_eth_required": 0.05,
        "key_actions": [
            "在 9 个不同自然月发起交互",
            "在 Arbitrum One 与 Nova 均有活动",
            "通过官方原生跨链桥入金 > $10,000",
            "快照时钱包保留至少 0.05 ETH 杜绝 0 余额被扫",
        ],
    },
    {
        "airdrop_id": "layerzero_top_tier",
        "name": "LayerZero ($ZRO) 跨链全满档",
        "top_reward_tokens": "5,000+ ZRO (~$22,500)",
        "active_months_required": 11,
        "total_txs_required": 90,
        "distinct_contracts_required": 45,
        "bridged_volume_usd_required": 25000.0,
        "retained_balance_eth_required": 0.10,
        "key_actions": [
            "跨越 8 条以上不同目标公链 (Non-EVM + EVM)",
            "使用 Stargate, Aptos Bridge, Testnet Bridge",
            "累计向合约支付 > $150 真实跨链手续费",
            "每月规律交互，绝不集中在某一周内突击刷单",
        ],
    },
    {
        "airdrop_id": "zksync_top_tier",
        "name": "ZKsync Era ($ZK) 生态重度玩家",
        "top_reward_tokens": "100,000 ZK (~$18,000)",
        "active_months_required": 8,
        "total_txs_required": 80,
        "distinct_contracts_required": 35,
        "bridged_volume_usd_required": 15000.0,
        "retained_balance_eth_required": 0.08,
        "key_actions": [
            "在 Era 存放资产借贷 (ZeroLend, SyncSwap LP)",
            "在 ZKsync Lite 与 Era 双向留存印记",
            "拥有至少 1 个 Paymaster 赞助交易",
            "Libertas Omnibus 社区勋章持有者",
        ],
    },
]


# 模块级预构建哈希索引表，实现 O(1) 毫秒级基准匹配
_BENCHMARK_MAP: dict[str, dict[str, Any]] = {b["airdrop_id"]: b for b in HISTORICAL_WHALE_BENCHMARKS}


def list_whale_benchmarks() -> list[dict[str, Any]]:
    """获取所有历史顶级空投胜利者行为基准."""
    return HISTORICAL_WHALE_BENCHMARKS


def compare_wallet_with_whale(
    benchmark_id: str = "arbitrum_top_tier",
    user_active_months: int = 4,
    user_total_txs: int = 25,
    user_contracts: int = 12,
    user_bridged_usd: float = 3200.0,
    user_retained_eth: float = 0.02,
    target_project: str = "Monad",
) -> dict[str, Any]:
    """对比用户当前钱包数据与顶级巨鲸基准，计算匹配度与补刀清单 (O(1) 哈希快速比对)."""
    bm = _BENCHMARK_MAP.get(benchmark_id, HISTORICAL_WHALE_BENCHMARKS[0])
    
    # 计算各项达标百分比
    r_months = min(1.0, user_active_months / max(1, bm["active_months_required"]))
    r_txs = min(1.0, user_total_txs / max(1, bm["total_txs_required"]))
    r_contracts = min(1.0, user_contracts / max(1, bm["distinct_contracts_required"]))
    r_volume = min(1.0, user_bridged_usd / max(1.0, bm["bridged_volume_usd_required"]))
    r_balance = min(1.0, user_retained_eth / max(0.001, bm["retained_balance_eth_required"]))
    
    # 综合匹配得分 (0 - 100)
    composite_score = round((r_months * 0.25 + r_txs * 0.20 + r_contracts * 0.25 + r_volume * 0.15 + r_balance * 0.15) * 100, 1)

    gap_details = [
        {
            "dimension": "活跃月份跨度",
            "user_val": f"{user_active_months} 个月",
            "whale_val": f"{bm['active_months_required']} 个月",
            "status": "PASS" if r_months >= 1.0 else "GAP",
            "gap_advice": f"还需在未来 {bm['active_months_required'] - user_active_months} 个自然月各保持至少 2 笔真实活动" if r_months < 1.0 else "已达到顶级巨鲸标准",
        },
        {
            "dimension": "独立智能合约",
            "user_val": f"{user_contracts} 个",
            "whale_val": f"{bm['distinct_contracts_required']} 个",
            "status": "PASS" if r_contracts >= 1.0 else "GAP",
            "gap_advice": f"需再寻找 {bm['distinct_contracts_required'] - user_contracts} 个新 DApp 丰富足迹 (DEX/借贷/NFT/跨链)" if r_contracts < 1.0 else "合约丰富度极佳",
        },
        {
            "dimension": "累计交互频次",
            "user_val": f"{user_total_txs} 笔",
            "whale_val": f"{bm['total_txs_required']} 笔",
            "status": "PASS" if r_txs >= 1.0 else "GAP",
            "gap_advice": f"还差 {bm['total_txs_required'] - user_total_txs} 笔，建议每周低 Gas 时段平滑补刀 2-3 笔" if r_txs < 1.0 else "笔数充足",
        },
        {
            "dimension": "跨链资金体量",
            "user_val": f"${user_bridged_usd:.0f}",
            "whale_val": f"${bm['bridged_volume_usd_required']:.0f}",
            "status": "PASS" if r_volume >= 1.0 else "GAP",
            "gap_advice": f"建议单笔大额或反复循环增加 ${bm['bridged_volume_usd_required'] - user_bridged_usd:.0f} 跨链流水" if r_volume < 1.0 else "过桥流水已满档",
        },
        {
            "dimension": "快照留存余额",
            "user_val": f"{user_retained_eth:.3f} ETH",
            "whale_val": f"{bm['retained_balance_eth_required']:.2f} ETH",
            "status": "PASS" if r_balance >= 1.0 else "GAP",
            "gap_advice": "务必常驻 > 0.05 ETH，禁止在刷完后把钱包提成 0 余额（极易被反女巫系统打死）" if r_balance < 1.0 else "底仓健康",
        },
    ]

    return {
        "benchmark_used": bm["name"],
        "target_project": target_project,
        "match_score": composite_score,
        "match_tier": "TOP_WHALE_TIER" if composite_score >= 85 else "ACTIVE_HUNTER" if composite_score >= 60 else "NEEDS_UPGRADE",
        "gap_analysis": gap_details,
        "action_plan_for_target": [
            f"针对 {target_project}：制定 6 个月持续周期计划，分散在每周四/周日低 Gas 交互",
            "不要只重复使用同一种 DEX Swap，增加流动性质押与跨链消息传递",
            "快照前绝不提光钱包资金，保留至少 $100 等值原生 Gas",
        ],
    }
