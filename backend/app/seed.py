"""Seed data module — fallback when external collectors are unavailable.

当所有外部采集源（DefiLlama / CryptoRank / Twitter / GitHub …）全部失败时，
本模块提供内置种子项目集，使 POST /run 仍能产出可评分的项目并写入 DB。

种子项目特征：
- source='seed'：标记为种子数据而非采集数据
- fetched_at=NULL：因为没有外部抓取行为
- 含 token 线索（funding_total_usd / funding_investors / funding_tier 等），
  供 §6.5 token_risk 启发式使用

数据维护策略（2026-09 刷新）：
- 真实项目条目只保留**仍然为真**的事实（融资、社交、代码库），发币状态
  随刷新更正。已发币且空投已结束的项目不再携带 testnet / points /
  task portal / explicit_airdrop 信号 —— 此前正是这些过时信号让
  ZKsync / Berachain 等长期以 FARM 标签污染扫描结果。
- 真实项目全部发币后，fallback 演示所需的 pre-TGE 信号覆盖（testnet /
  points / no_token_yet）由**显式合成条目**承担（example.com 域名，
  与 Galaxy Gaming Chain 同一模式），不对应任何真实项目。
- get_seed_raw_projects 与 collect_from_repository 保持同一过滤口径：
  "已发币且无空投信号"的条目不进入流水线（见函数注释）。

Reference:
- ENGINEERING_ROADMAP.md §10.2「Collector 全量失败回退 seed」
- V2_TASKS.md B2
"""

from __future__ import annotations

from typing import Any

import structlog

from app.agents.base import RawProject
from app.agents.collector import CollectorAgent
from app.collectors.noise import is_listed_token_no_airdrop_signals

logger = structlog.get_logger(__name__)

# ── 种子数据集 ──────────────────────────────────
# 两段结构：真实项目（已发币，作为过滤夹具保留）+ 合成 pre-TGE 项目（演示覆盖）。
# 字段经 _raw_to_record → _infer_airdrop_flags 正常走采集器归一化路径，
# 因此 funding_* 字段会被 extract_funding_from_raw 提取。

SEED_PROJECTS: list[dict[str, Any]] = [
    # ── 真实项目：2026-09 状态刷新，代币均已上线、空投均已结束 ──
    # 不携带任何空投信号；保留在列表里作为 get_seed_raw_projects
    # 过滤路径的夹具（它们会被筛掉），融资/社交字段仍是事实。
    {
        "name": "EigenLayer Pro",
        "url": "https://eigenlayer.pro",
        "sector": "Restaking",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": False,  # EIGEN TGE 2024-10
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
        "recent_funding": True,
        "tvl_usd": 15_000_000,
        "description": "Restaking protocol; EIGEN token tradable since Oct 2024",
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
        "no_token_yet": False,  # SCR TGE 2024-10
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
        "recent_funding": True,
        "tvl_usd": 800_000_000,
        "description": "zkEVM rollup; SCR token tradable since Oct 2024",
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
        "has_points_program": False,
        "no_token_yet": False,  # ZRO TGE 2024-06
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
        "recent_funding": True,
        "tvl_usd": 200_000_000,
        "description": "Omnichain messaging protocol; ZRO token tradable since Jun 2024",
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
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": False,  # BERA TGE 2025-02
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
        "recent_funding": True,
        "tvl_usd": 5_000_000,
        "description": "Proof of liquidity L1; BERA token tradable since Feb 2025",
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
        "no_token_yet": False,  # TIA TGE 2023-10
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
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
        "has_points_program": False,  # 积分/空投均已结束
        "no_token_yet": False,  # ZK TGE 2024-06
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
        "recent_funding": True,
        "tvl_usd": 600_000_000,
        "description": "ZK rollup; ZK token tradable since Jun 2024",
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
        "name": "Pyth Network",
        "url": "https://pyth.network",
        "sector": "Oracle",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": False,  # PYTH TGE 2023-11
        "explicit_airdrop_mention": False,
        "has_task_portal": False,
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
    # ── 合成 pre-TGE 项目：显式演示数据（example.com），不对应真实项目 ──
    # 真实项目全部发币后，fallback 演示的 testnet / points / no_token_yet
    # 信号覆盖由这些条目承担。
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
        "name": "Aurelia Oracle",
        "url": "https://aurelia-oracle.example.com",
        "sector": "Oracle",
        "stage": "testnet",
        "source": "seed",
        "has_testnet": True,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": 3_500_000,
        "description": "Synthetic seed entry: oracle network in testnet, points program, pre-TGE",
        "has_docs": True,
        "has_twitter": True,
        "sybil_friction": "medium",
        "funding_total_usd": 18_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2026-03-18",
        "funding_investors": ["Placeholder", "1kx"],
        "funding_lead_investors": ["Placeholder"],
        "funding_tier": "tier1",
    },
    {
        "name": "Meridian Restaking",
        "url": "https://meridian-restaking.example.com",
        "sector": "Restaking",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": 9_000_000,
        "description": "Synthetic seed entry: restaking protocol live without token, points program running",
        "has_github": True,
        "github_stars": 900,
        "sybil_friction": "high",
        "funding_total_usd": 27_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2026-01-22",
        "funding_investors": ["Electric Capital", "1kx", "Robot Ventures"],
        "funding_lead_investors": ["Electric Capital"],
        "funding_tier": "tier1",
    },
    {
        "name": "Vector Modular DA",
        "url": "https://vector-modular.example.com",
        "sector": "Infra",
        "stage": "mainnet",
        "source": "seed",
        "has_testnet": False,
        "has_points_program": False,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": None,
        "description": "Synthetic seed entry: modular data availability layer, pre-TGE with docs and audits",
        "has_docs": True,
        "has_whitepaper": True,
        "has_twitter": True,
        "funding_total_usd": 35_000_000,
        "funding_rounds": 2,
        "funding_last_date": "2026-05-30",
        "funding_investors": ["Framework", "Pantera"],
        "funding_lead_investors": ["Framework"],
        "funding_tier": "tier1",
    },
    {
        "name": "Quanta ZK",
        "url": "https://quanta-zk.example.com",
        "sector": "ZK",
        "stage": "testnet",
        "source": "seed",
        "has_testnet": True,
        "has_points_program": False,
        "no_token_yet": True,
        "recent_funding": True,
        "tvl_usd": None,
        "description": "Synthetic seed entry: ZK coprocessor in testnet, no token yet",
        "has_github": True,
        "github_stars": 420,
        "funding_total_usd": 8_000_000,
        "funding_rounds": 1,
        "funding_last_date": "2026-07-01",
        "funding_investors": ["Robot Ventures"],
        "funding_lead_investors": ["Robot Ventures"],
        "funding_tier": "tier1",
    },
]


def get_seed_raw_projects() -> list[RawProject]:
    """Return seed projects as RawProject objects for pipeline fallback.

    产出物的关键属性：
    - source='seed'（由 _raw_to_record 从 raw["source"] 继承）
    - created_at=None → 落库时 fetched_at=NULL（§5 表注释要求）
    - 走正常 collect_from_seed → _dedup_records 路径，保持归一化一致
    - 与 collect_from_repository 同口径过滤"已发币且无空投信号"的条目

    过滤只挂在本 fallback 入口，不挂 collect_from_seed 本身：后者还服务于
    POST /run 的用户自提交项目，显式输入必须允许进入评分（由 eligibility
    veto 在评分层给出 IGNORE/降级），不能在采集层静默丢弃。

    Returns:
        去重、过滤后的 RawProject 列表
    """
    collector = CollectorAgent()
    projects = collector.collect_from_seed(SEED_PROJECTS)

    # fetched_at = project.created_at 在 repository 的 INSERT 中映射。
    # seed 数据没有外部抓取行为，故强制 created_at=None 使 fetched_at 为 NULL。
    for p in projects:
        p.created_at = None  # type: ignore[assignment]
        # source 已经是 'seed'（由 _raw_to_record 从 raw["source"] 继承）

    # 已发币过滤（2026-09 修复）：此前 seed 路径完全绕过该过滤，过时的
    # no_token_yet/explicit_airdrop 字段让已发币项目以 FARM 标签写库。
    # seed 无库表可隔离，直接在内存里过滤。
    filtered = [
        p
        for p in projects
        if not is_listed_token_no_airdrop_signals(
            no_token_yet=p.no_token_yet,
            has_testnet=p.has_testnet,
            has_points_program=p.has_points_program,
            has_task_portal=p.has_task_portal,
            explicit_airdrop_mention=p.explicit_airdrop_mention,
            source_id="seed",
        )
    ]

    logger.info(
        "seed.fallback_loaded",
        count=len(filtered),
        input_count=len(projects),
        launched_filtered=len(projects) - len(filtered),
    )
    return filtered
