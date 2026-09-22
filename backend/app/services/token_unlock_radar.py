"""Token Unlock Radar Service (代币归属解锁与悬崖抛压雷达).

跟踪主流 Web3 项目的代币解锁时间线、悬崖释放量 (Cliff)、占流通比例与市场抛压评级。
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any
import structlog

logger = structlog.get_logger(__name__)

# 预设知名空投与头部协议解锁数据库
_INITIAL_UNLOCKS: list[dict[str, Any]] = [
    {
        "project_id": "celestia",
        "project_name": "Celestia",
        "token_symbol": "TIA",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=12)).strftime("%Y-%m-%d"),
        "unlock_type": "cliff",
        "amount_tokens": 175_560_000,
        "usd_value_estimate": 875_000_000.0,
        "circulating_supply_pct": 16.3,
        "total_supply_pct": 17.5,
        "unlocked_for": ["种子轮投资人 (Seed)", "A轮领投机构", "早期核心贡献者"],
        "pressure_rating": "critical",
        "analysis_summary": "早期 VC 与核心团队大额首期悬崖解锁，释放量占流通盘 16.3%，抛压集中度极高，建议对冲或规避短期现货波动。",
        "action_advice": "衍生品资金费率通常在解锁日前 3-5 天走负，建议持有者提前锁定利润或建立保护性看跌期权。"
    },
    {
        "project_id": "wormhole",
        "project_name": "Wormhole",
        "token_symbol": "W",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=18)).strftime("%Y-%m-%d"),
        "unlock_type": "cliff",
        "amount_tokens": 600_000_000,
        "usd_value_estimate": 150_000_000.0,
        "circulating_supply_pct": 33.3,
        "total_supply_pct": 6.0,
        "unlocked_for": ["生态系统基金", "战略合作支持者"],
        "pressure_rating": "critical",
        "analysis_summary": "生态基金单次释放量超当前流通盘 30%，即使部分流入流动性池，仍可能产生较强二级市场流动性挤压。",
        "action_advice": "关注链上基金会多签钱包是否有大额充值至币安/OKX 的异动。"
    },
    {
        "project_id": "layerzero",
        "project_name": "LayerZero",
        "token_symbol": "ZRO",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=25)).strftime("%Y-%m-%d"),
        "unlock_type": "cliff",
        "amount_tokens": 24_690_000,
        "usd_value_estimate": 88_500_000.0,
        "circulating_supply_pct": 9.8,
        "total_supply_pct": 2.5,
        "unlocked_for": ["早期战略轮投资人", "顾问团队"],
        "pressure_rating": "high",
        "analysis_summary": "早期战略轮到期解锁，释放量约占流通盘近 10%，抛压评级为高，需重点关注场外 OTC 交易折价率。",
        "action_advice": "空投猎人若持有空投币，可在解锁日前阶段性分批止盈。"
    },
    {
        "project_id": "starknet",
        "project_name": "Starknet",
        "token_symbol": "STRK",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=32)).strftime("%Y-%m-%d"),
        "unlock_type": "linear",
        "amount_tokens": 64_000_000,
        "usd_value_estimate": 28_800_000.0,
        "circulating_supply_pct": 7.2,
        "total_supply_pct": 0.64,
        "unlocked_for": ["早期贡献者与投资者线性释放"],
        "pressure_rating": "high",
        "analysis_summary": "月度常规线性解锁，市场已形成一定消化预期，但整体流通盘供给仍处于持续膨胀周期。",
        "action_advice": "适合逢低定投做波段，不宜盲目左侧扛单。"
    },
    {
        "project_id": "arbitrum",
        "project_name": "Arbitrum",
        "token_symbol": "ARB",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=45)).strftime("%Y-%m-%d"),
        "unlock_type": "linear",
        "amount_tokens": 92_650_000,
        "usd_value_estimate": 46_325_000.0,
        "circulating_supply_pct": 3.2,
        "total_supply_pct": 0.92,
        "unlocked_for": ["Offchain Labs 团队", "DAO 治理金库"],
        "pressure_rating": "moderate",
        "analysis_summary": "ARB 月度匀速线性释放，占流通市值约 3.2%，现货深度与做市商承接能力良好，属于温和抛压范畴。",
        "action_advice": "影响相对有限，建议结合全链以太坊生态行情与 L2 叙事综合决策。"
    },
    {
        "project_id": "zksync",
        "project_name": "ZKsync",
        "token_symbol": "ZK",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=60)).strftime("%Y-%m-%d"),
        "unlock_type": "linear",
        "amount_tokens": 166_660_000,
        "usd_value_estimate": 23_300_000.0,
        "circulating_supply_pct": 4.5,
        "total_supply_pct": 0.8,
        "unlocked_for": ["Matter Labs 核心团队", "生态孵化支持"],
        "pressure_rating": "moderate",
        "analysis_summary": "团队与生态月度释放，金额适中，主要抛压取决于当时 L2 活跃度与空投第二期预期。",
        "action_advice": "若有链上流动性质押或借贷需求，可在解锁前利用借贷协议做现货对冲。"
    },
    {
        "project_id": "story-protocol",
        "project_name": "Story Protocol",
        "token_symbol": "IP",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%Y-%m-%d"),
        "unlock_type": "cliff",
        "amount_tokens": 50_000_000,
        "usd_value_estimate": 125_000_000.0,
        "circulating_supply_pct": 5.0,
        "total_supply_pct": 5.0,
        "unlocked_for": ["创世社区空投 (Genesis Drop)", "生态共建奖励"],
        "pressure_rating": "moderate",
        "analysis_summary": "TGE 初始创世释放模型，空投筹码多为散户持有，开盘首日可能存在集中抛压，后续生态锁仓计划良好。",
        "action_advice": "空投猎人建议开盘当天首小时观察流动性池深度，执行分批止盈。"
    },
    {
        "project_id": "monad",
        "project_name": "Monad",
        "token_symbol": "MON",
        "unlock_date": (datetime.now(timezone.utc) + timedelta(days=120)).strftime("%Y-%m-%d"),
        "unlock_type": "cliff",
        "amount_tokens": 100_000_000,
        "usd_value_estimate": 250_000_000.0,
        "circulating_supply_pct": 10.0,
        "total_supply_pct": 10.0,
        "unlocked_for": ["初始空投分发", "早期流动性引导"],
        "pressure_rating": "high",
        "analysis_summary": "顶级 EVM 并行公链上线初期流动性释放，高估值预期可能伴随早期套利者快速套现。",
        "action_advice": "早期关注官方质押节点年化收益率 (APR)，若质押率 > 60% 则可考虑部分长期复投。"
    }
]


def calculate_pressure_rating(circulating_pct: float, usd_value: float) -> str:
    """根据流通占比和预估释放金额综合评估抛压风险."""
    if circulating_pct >= 15.0 or usd_value >= 100_000_000.0:
        return "critical"
    elif circulating_pct >= 6.0 or usd_value >= 30_000_000.0:
        return "high"
    elif circulating_pct >= 2.0 or usd_value >= 10_000_000.0:
        return "moderate"
    return "low"


def get_upcoming_unlocks(
    limit: int = 20,
    min_pressure: str | None = None,
    sort_by: str = "date"
) -> list[dict[str, Any]]:
    """获取即将到来的代币解锁列表，支持按抛压等级过滤和排序."""
    pressure_hierarchy = {"critical": 4, "high": 3, "moderate": 2, "low": 1}
    min_score = pressure_hierarchy.get(min_pressure.lower(), 1) if min_pressure else 1

    filtered = [
        u for u in _INITIAL_UNLOCKS
        if pressure_hierarchy.get(u.get("pressure_rating", "low"), 1) >= min_score
    ]

    if sort_by == "value":
        filtered.sort(key=lambda x: x.get("usd_value_estimate", 0), reverse=True)
    elif sort_by == "pct":
        filtered.sort(key=lambda x: x.get("circulating_supply_pct", 0), reverse=True)
    else:  # date
        filtered.sort(key=lambda x: x.get("unlock_date", ""))

    return filtered[:limit]


def get_project_unlock_details(project_id: str) -> dict[str, Any] | None:
    """根据项目 ID 查询其专属代币解锁详情与抛压建议."""
    pid = project_id.lower().strip()
    for u in _INITIAL_UNLOCKS:
        if u["project_id"] == pid or pid in u["project_id"]:
            return u
    return None
