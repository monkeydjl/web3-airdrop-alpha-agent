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

            # Get sector profile (static baseline)
            profile = SECTOR_PROFILE.get(sector, DEFAULT_PROFILE)

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
