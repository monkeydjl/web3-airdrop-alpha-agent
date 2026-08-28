"""Seed data module — fallback when external collectors are unavailable.

当所有外部采集源（DefiLlama / CryptoRank / Twitter / GitHub …）全部失败时，
本模块提供内置种子项目集，使 POST /run 仍能产出可评分的项目并写入 DB。

种子项目特征：
- source='seed'：标记为种子数据而非采集数据
- fetched_at=NULL：因为没有外部抓取行为
- 含 token 线索（funding_total_usd / funding_investors / funding_tier 等），
  供 §6.5 token_risk 启发式使用

Reference:
- ENGINEERING_ROADMAP.md §10.2「Collector 全量失败回退 seed」
- V2_TASKS.md B2
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import RawProject
from app.agents.collector import CollectorAgent

logger = structlog.get_logger(__name__)

# ── 种子数据集 ──────────────────────────────────
# 8 个项目，覆盖主要赛道，含 token 线索供 token_risk 启发式。
# 字段经 _raw_to_record → _infer_airdrop_flags 正常走采集器归一化路径，
# 因此 funding_* 字段会被 extract_funding_from_raw 提取。

SEED_PROJECTS: list[dict[str, Any]] = [
    {
        "name": "EigenLayer Pro",
        "url": "https://eigenlayer.pro",
        "sector": "Restaking",
        "stage": "testnet",
        "source": "seed",
        "has_testnet": True,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": 15_000_000,
        "description": "Restaking protocol with points program and confirmed airdrop",
        "explicit_airdrop_mention": True,
        "has_task_portal": True,
        "sybil_friction": "medium",
        "funding_total_usd": 64_000_000,
        "funding_rounds": 3,
        "funding_last_date": "2025-08-15",
        "funding_investors": ["a16z", "Paradigm", "Coinbase Ventures"],
        "funding_lead_investors": ["a16z"],
        "funding_tier": "tier1",
    },
    {
        "name": "Scroll zkEVM",
        "url": "https://scroll.io",
        "sector": "ZK",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": 800_000_000,
        "description": "zkEVM rollup, mainnet live, no token yet",
        "has_github": True,
        "github_stars": 12000,
        "has_docs": True,
        "has_twitter": True,
        "funding_total_usd": 80_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2025-10-01",
        "funding_investors": ["Polychain", "Sequoia", "Bain Capital"],
        "funding_lead_investors": ["Polychain"],
        "funding_tier": "tier1",
    },
    {
        "name": "LayerZero V2",
        "url": "https://layerzero.network",
        "sector": "Bridge",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": True,
        "no_token_yet": False,
        "recent_funding": True,
        "tvl_usd": 200_000_000,
        "description": "Omnichain messaging protocol with points and token",
        "has_task_portal": True,
        "explicit_airdrop_mention": True,
        "sybil_friction": "high",
        "funding_total_usd": 135_000_000,
        "funding_rounds": 3,
        "funding_last_date": "2025-09-20",
        "funding_investors": ["a16z", "Sequoia", "Samsung Next"],
        "funding_lead_investors": ["a16z"],
        "funding_tier": "tier1",
    },
    {
        "name": "Berachain",
        "url": "https://berachain.com",
        "sector": "DeFi",
        "stage": "testnet",
        "source": "seed",
        "has_testnet": True,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": 5_000_000,
        "description": "Proof of liquidity chain, testnet with points program",
        "has_github": True,
        "github_stars": 3500,
        "has_discord": True,
        "has_twitter": True,
        "funding_total_usd": 114_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2025-04-06",
        "funding_investors": ["Polychain", "Hack VC", "Shima Capital"],
        "funding_lead_investors": ["Polychain"],
        "funding_tier": "tier1",
    },
    {
        "name": "Celestia Modular",
        "url": "https://celestia.org",
        "sector": "Infra",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": False,
        "recent_funding": True,
        "tvl_usd": 500_000_000,
        "description": "Modular data availability layer, mainnet with token",
        "has_github": True,
        "github_stars": 8000,
        "has_docs": True,
        "has_whitepaper": True,
        "has_roadmap": True,
        "funding_total_usd": 55_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2024-10-22",
        "funding_investors": ["Bain Capital", "Jump Crypto", "Coinbase Ventures"],
        "funding_lead_investors": ["Bain Capital"],
        "funding_tier": "tier2",
    },
    {
        "name": "ZKsync Era",
        "url": "https://zksync.io",
        "sector": "ZK",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": True,
        "no_token_yet": False,
        "recent_funding": True,
        "tvl_usd": 600_000_000,
        "description": "ZK rollup with points program and token airdrop completed",
        "explicit_airdrop_mention": True,
        "has_github": True,
        "github_stars": 15000,
        "has_docs": True,
        "has_twitter": True,
        "funding_total_usd": 458_000_000,
        "funding_rounds": 3,
        "funding_last_date": "2024-11-19",
        "funding_investors": ["a16z", "Dragonfly", "Lightspeed"],
        "funding_lead_investors": ["a16z"],
        "funding_tier": "tier1",
    },
    {
        "name": "Galaxy Gaming Chain",
        "url": "https://galaxy-gaming.example.com",
        "sector": "Gaming",
        "stage": "testnet",
        "source": "seed",
        "has_testnet": True,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": False,
        "tvl_usd": None,
        "description": "Web3 gaming platform, testnet with points program",
        "has_task_portal": True,
        "has_discord": True,
        "has_twitter": True,
        "sybil_friction": "low",
        "funding_total_usd": 12_000_000,
        "funding_rounds": 1,
        "funding_last_date": "2025-01-10",
        "funding_investors": ["Animoca", "Spartan"],
        "funding_lead_investors": ["Animoca"],
        "funding_tier": "tier2",
    },
    {
        "name": "Pyth Network",
        "url": "https://pyth.network",
        "sector": "Oracle",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": False,
        "recent_funding": True,
        "tvl_usd": 300_000_000,
        "description": "Real-time oracle network, mainnet with token",
        "has_github": True,
        "github_stars": 5000,
        "has_docs": True,
        "has_whitepaper": True,
        "has_roadmap": True,
        "funding_total_usd": 52_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2024-08-12",
        "funding_investors": ["Multicoin", "Jump Crypto", "Wintermute"],
        "funding_lead_investors": ["Multicoin"],
        "funding_tier": "tier2",
    },
]


def get_seed_raw_projects() -> list[RawProject]:
    """Return seed projects as RawProject objects for pipeline fallback.

    产出物的关键属性：
    - source='seed'（由 _raw_to_record 从 raw["source"] 继承）
    - created_at=None → 落库时 fetched_at=NULL（§5 表注释要求）
    - 走正常 collect_from_seed → _dedup_records 路径，保持归一化一致

    Returns:
        去重后的 RawProject 列表
    """
    collector = CollectorAgent()
    projects = collector.collect_from_seed(SEED_PROJECTS)

    # fetched_at = project.created_at 在 repository 的 INSERT 中映射。
    # seed 数据没有外部抓取行为，故强制 created_at=None 使 fetched_at 为 NULL。
    for p in projects:
        p.created_at = None  # type: ignore[assignment]
        # source 已经是 'seed'（由 _raw_to_record 从 raw["source"] 继承）

    logger.info("seed.fallback_loaded", count=len(projects))
    return projects
