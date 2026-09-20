"""Narrative Agent - Sector cycle analysis.

Analyzes which stage of the narrative cycle a project's sector is in.
Determines heat score and optimal timing for participation.

Reference:
- ENGINEERING_ROADMAP.md §6.3 Narrative Engine
- DATA_SCORING_DICT.md §3.1 NarrativeResult
"""

import time
from typing import Any

import structlog

from app import metrics
from app.agents.base import AgentError, BaseAgent, PipelineState
from app.agents.heat_signals import HeatSignalProvider, get_heat_signal_provider
from app.models import NarrativeResult

logger = structlog.get_logger(__name__)


# Sector profile configuration
# Format: sector -> {base_heat, stage, momentum}
SECTOR_PROFILE: dict[str, dict[str, Any]] = {
    # Layer 2
    "L2": {
        "base_heat": 0.85,
        "stage": "growth",
        "momentum": 1.1,
    },
    "Layer2": {
        "base_heat": 0.85,
        "stage": "growth",
        "momentum": 1.1,
    },
    # Restaking (hot narrative)
    "Restaking": {
        "base_heat": 0.90,
        "stage": "peak",
        "momentum": 1.2,
    },
    # DeFi
    "DeFi": {
        "base_heat": 0.70,
        "stage": "mature",
        "momentum": 0.9,
    },
    "DEX": {
        "base_heat": 0.65,
        "stage": "mature",
        "momentum": 0.85,
    },
    "Lending": {
        "base_heat": 0.60,
        "stage": "mature",
        "momentum": 0.8,
    },
    # Gaming
    "Gaming": {
        "base_heat": 0.75,
        "stage": "growth",
        "momentum": 1.0,
    },
    "GameFi": {
        "base_heat": 0.70,
        "stage": "growth",
        "momentum": 0.95,
    },
    # Infrastructure
    "Infrastructure": {
        "base_heat": 0.80,
        "stage": "growth",
        "momentum": 1.05,
    },
    "Bridge": {
        "base_heat": 0.55,
        "stage": "mature",
        "momentum": 0.75,
    },
    # Privacy / ZK
    "Privacy": {
        "base_heat": 0.78,
        "stage": "growth",
        "momentum": 1.0,
    },
    "ZK": {
        "base_heat": 0.82,
        "stage": "growth",
        "momentum": 1.1,
    },
    # AI
    "AI": {
        "base_heat": 0.88,
        "stage": "early",
        "momentum": 1.3,
    },
    # NFT
    "NFT": {
        "base_heat": 0.50,
        "stage": "mature",
        "momentum": 0.7,
    },
    # DAO
    "DAO": {
        "base_heat": 0.55,
        "stage": "mature",
        "momentum": 0.8,
    },
}

# Default profile for unknown sectors
DEFAULT_PROFILE = {
    "base_heat": 0.60,
    "stage": "growth",
    "momentum": 1.0,
}


# 查表侧的写法归一。**只用于查 SECTOR_PROFILE，不改写 project.sector。**
#
# 为什么不去扩 utils.normalize.SECTOR_ALIAS：那个函数的产出进了
# `create_dedup_key()` → `generate_deterministic_id()`，sector 是项目确定性 ID
# 的组成部分。把 "Dexes" 归一成 "DEX" 会让同一个项目算出不同的 UUID，既有行
# 全部变成孤儿、去重失效。归一必须留在查表这一侧。
#
# 键是 lower() 后的形式；值必须是 SECTOR_PROFILE 里真实存在的键
# （由 test_narrative.py 的一致性测试保证，写错会红灯而不是静默走默认档）。
_SECTOR_LOOKUP_ALIAS: dict[str, str] = {
    # L2 / rollup 家族：DefiLlama 用 "Rollup"，CryptoRank 用 "Layer 2"
    "layer2": "L2",
    "layer 2": "L2",
    "layer-2": "L2",
    "l2": "L2",
    "rollup": "L2",
    "rollups": "L2",
    "optimistic rollup": "L2",
    # ZK
    "zk": "ZK",
    "zk rollup": "ZK",
    "zk-rollup": "ZK",
    "zero-knowledge": "ZK",
    "zkevm": "ZK",
    # DEX：DefiLlama 的 category 是复数 "Dexes"
    "dex": "DEX",
    "dexes": "DEX",
    "dexs": "DEX",
    "decentralized exchange": "DEX",
    "derivatives": "DEX",
    "perpetuals": "DEX",
    "perp-dex": "DEX",
    "dex-aggregator": "DEX",
    # Restaking：LRT 赛道在 DefiLlama 里叫 "Liquid Restaking"
    "restaking": "Restaking",
    "liquid restaking": "Restaking",
    "liquid restaking tokens": "Restaking",
    "re-staking": "Restaking",
    "restake": "Restaking",
    # Lending / CDP
    "lending": "Lending",
    "cdp": "Lending",
    "borrowing": "Lending",
    # Bridge
    "bridge": "Bridge",
    "cross chain": "Bridge",
    "cross-chain": "Bridge",
    "interoperability": "Bridge",
    # Infrastructure：模块化 / DA / 预言机 / 通用链都归这档
    "infra": "Infrastructure",
    "infrastructure": "Infrastructure",
    "chain": "Infrastructure",
    "modular": "Infrastructure",
    "modular-da": "Infrastructure",
    "modular-execution": "Infrastructure",
    "data availability": "Infrastructure",
    "oracle": "Infrastructure",
    "oracles": "Infrastructure",
    "services": "Infrastructure",
    "l1": "Infrastructure",
    # DeFi 泛类
    "defi": "DeFi",
    "de-fi": "DeFi",
    "yield": "DeFi",
    "farm": "DeFi",
    "liquid staking": "DeFi",
    "staking": "DeFi",
    # Gaming
    "gaming": "Gaming",
    "game": "Gaming",
    "games": "Gaming",
    "gamefi": "GameFi",
    # Privacy
    "privacy": "Privacy",
    "privacy-rollup": "Privacy",
    # 其余单键归一（大小写 / 复数）
    "ai": "AI",
    "artificial intelligence": "AI",
    "nft": "NFT",
    "nfts": "NFT",
    "dao": "DAO",
    "daos": "DAO",
}


def canonical_sector_key(sector: str | None) -> str | None:
    """把 sector 的各种写法折成规范键，未知写法原样返回。

    与 `resolve_sector_profile()` 共用同一张别名表，但用途不同：这个函数用于
    **按赛道分组**（competition 子分的 sector_count），而不是查热度档位。

    与查档位一样，**不改写 `project.sector`** —— 那个值参与
    `generate_deterministic_id()`，改了会让既有项目 ID 漂移。

    未知写法返回 trim 后的原值而不是 None：分组场景下「不认识的赛道」仍然是
    一个合法的独立分组，不能塌成同一个 None 桶 —— 那会把 RWA 和 SocialFi 算成
    同一个赛道的竞品。
    """
    if not sector:
        return sector

    stripped = sector.strip()
    if not stripped:
        return stripped

    if stripped in SECTOR_PROFILE:
        return stripped

    key = stripped.lower()

    canonical = _SECTOR_LOOKUP_ALIAS.get(key)
    if canonical is not None:
        return canonical

    for profile_key in SECTOR_PROFILE:
        if profile_key.lower() == key:
            return profile_key

    return stripped


def resolve_sector_profile(sector: str) -> tuple[dict[str, Any], str | None]:
    """查 SECTOR_PROFILE，返回 (profile, 命中的规范键)。

    未命中时返回 `(DEFAULT_PROFILE, None)` —— 第二个返回值是 None 让调用方能
    **区分「命中了」与「走了默认档」**，这正是原实现缺的东西：
    `SECTOR_PROFILE.get(sector, DEFAULT_PROFILE)` 未命中时静默返回默认档，
    `DEFAULT_PROFILE` 又恰好让 narrative_timing 恒等于 60.0，于是这一维的
    0.15 权重退化成常数，且没有任何信号提示。

    三级查找，全部不改写 `project.sector` 本身：
    1. 精确匹配（已是规范键）
    2. lower() 后查别名表（吸收 "Dexes" / "Rollup" / "Layer 2" 这类真实写法）
    3. lower() 后与规范键的 lower() 比对（纯大小写差异，如 "l2" / "zk"）
    """
    if not sector:
        return DEFAULT_PROFILE, None

    if sector in SECTOR_PROFILE:
        return SECTOR_PROFILE[sector], sector

    key = sector.strip().lower()

    canonical = _SECTOR_LOOKUP_ALIAS.get(key)
    if canonical is not None:
        return SECTOR_PROFILE[canonical], canonical

    for profile_key in SECTOR_PROFILE:
        if profile_key.lower() == key:
            return SECTOR_PROFILE[profile_key], profile_key

    return DEFAULT_PROFILE, None


def stage_to_timing(stage: str) -> str:
    """Map lifecycle stage to timing.

    Args:
        stage: Lifecycle stage (early/growth/peak/mature)

    Returns:
        Timing (early/peak/late)

    Mapping:
        early -> early
        growth -> early
        peak -> peak
        mature -> late
    """
    mapping = {
        "early": "early",
        "growth": "early",
        "peak": "peak",
        "mature": "late",
    }
    return mapping.get(stage, "early")


class NarrativeAgent(BaseAgent):
    """Narrative Agent - Sector cycle analysis.

    MVP: Uses static SECTOR_PROFILE configuration
    V2 (C3): Adds real-time Twitter/VC/KOL signals via HeatSignalProvider
    """

    def __init__(self, heat_provider: HeatSignalProvider | None = None):
        super().__init__("narrative")
        # 允许注入自定义 provider（测试用）；否则用全局单例
        self._heat_provider = heat_provider

    def _get_heat_provider(self) -> HeatSignalProvider:
        """获取热度信号 provider（惰性初始化）。"""
        if self._heat_provider is not None:
            return self._heat_provider
        return get_heat_signal_provider()

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute narrative analysis.

        Args:
            state: Current pipeline state

        Returns:
            Updated state with narrative result
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Get sector
            sector = state.project.sector or "Unknown"

            # Get sector profile (static baseline).
            # 未命中要出声：默认档让 narrative_timing 恒等 60.0，等于把这一维的
            # 0.15 权重扔掉，而分数看上去完全正常 —— 没有日志就没人会发现。
            profile, matched_sector = resolve_sector_profile(sector)
            if matched_sector is None:
                self.logger.warning(
                    "narrative.sector_profile_missing",
                    project_id=state.project.id,
                    sector=sector,
                    known_sectors=sorted(SECTOR_PROFILE),
                    impact="narrative_timing 退化为默认档常数，该维权重实际未参与区分",
                )

            # Calculate base heat score
            base_heat = profile["base_heat"]
            momentum = profile["momentum"]
            stage = profile["stage"]

            # MVP: Simple momentum adjustment
            static_heat = min(1.0, base_heat * momentum)

            # V2 (C3): Apply dynamic heat signal multiplier
            # 失败时 multiplier=1.0，不影响静态 heat_score（降级路径）
            try:
                multiplier = self._get_heat_provider().get_multiplier(sector)
                heat_score = min(1.0, max(0.0, static_heat * multiplier))
            except Exception as e:
                self.logger.warning(
                    "narrative.heat_signal_failed",
                    project_id=state.project.id,
                    sector=sector,
                    error=str(e),
                    fallback="static_heat",
                )
                heat_score = static_heat

            # Map stage to timing
            timing = stage_to_timing(stage)

            # Create result
            result = NarrativeResult(
                sector=sector,
                stage=stage,
                heat_score=heat_score,
                timing=timing,
            )

            # Update state
            state.narrative = result

            metrics.record_narrative_heat_score(heat_score)

            self.logger.info(
                "narrative.completed",
                project_id=state.project.id,
                sector=sector,
                stage=stage,
                heat_score=round(heat_score, 2),
                timing=timing,
            )

        except Exception as e:
            error = AgentError(
                agent_name=self.name, kind="narrative_error", message=str(e), project_id=state.project.id
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state


if __name__ == "__main__":
    # Test narrative agent
    import asyncio

    from app.agents.base import AgentContext, RawProject

    async def test() -> None:
        print("=== Testing Narrative Agent ===\n")

        # Test cases
        test_projects = [
            ("LayerX", "L2"),
            ("EigenLayer", "Restaking"),
            ("UniswapX", "DEX"),
            ("Aave", "Lending"),
            ("WorldAI", "AI"),
            ("Unknown Project", "NewSector"),
        ]

        agent = NarrativeAgent()

        for name, sector in test_projects:
            project = RawProject(id=f"test-{name}", name=name, sector=sector, stage="testnet", source="seed")

            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            result_state = await agent.run(state)

            if result_state.narrative:
                n = result_state.narrative
                print(f"✓ {name} ({sector})")
                print(f"  Stage: {n.stage}")
                print(f"  Heat: {n.heat_score:.2f}")
                print(f"  Timing: {n.timing}")
                print()

        print("✓ All tests completed!")

    asyncio.run(test())
