"""Tokenomics Agent - Token economics analysis.

Analyzes token distribution, VC/team allocation, and unlock pressure.
Produces tokenomics risk score based on token structure.

Reference:
- ENGINEERING_ROADMAP.md §6.6 Tokenomics Analysis
- DATA_SCORING_DICT.md §3.4 TokenomicsResult
- DATA_SCORING_DICT.md §5.7.1 Tokenomics unlock_penalty mapping
"""

import time
from typing import Dict

import structlog

from app.agents.base import BaseAgent, PipelineState, AgentError
from app.models import TokenomicsResult

logger = structlog.get_logger(__name__)


# Unlock pressure to penalty mapping
# From DATA_SCORING_DICT.md §5.7.1
UNLOCK_PENALTY_MAP: Dict[str, float] = {
    "low": 0.15,
    "medium": 0.35,
    "high": 0.65,
}

# Default unlock penalty if pressure is unknown
DEFAULT_UNLOCK_PENALTY = 0.35


def estimate_vc_share(project: "RawProject") -> float:
    """Estimate VC share from project signals.

    MVP heuristic: Use funding and stage signals to estimate
    V2: Use real tokenomics data from documentation

    Args:
        project: Raw project data

    Returns:
        Estimated VC share (0.0-1.0)

    Heuristics:
        - Recent funding + mainnet -> 0.25 (moderate VC allocation)
        - Recent funding + testnet -> 0.30 (higher VC allocation)
        - No funding signals -> 0.20 (assume some seed funding)
        - Ideation with funding -> 0.35 (early stage, higher VC%)
    """
    if project.recent_funding:
        if project.stage == "mainnet":
            return 0.25
        elif project.stage == "testnet":
            return 0.30
        else:  # ideation
            return 0.35
    else:
        # No funding signal - assume lower VC allocation
        return 0.20


def estimate_team_share(project: "RawProject") -> float:
    """Estimate team share from project signals.

    MVP heuristic: Use stage and team signals
    V2: Use real tokenomics data from documentation

    Args:
        project: Raw project data

    Returns:
        Estimated team share (0.0-1.0)

    Heuristics:
        - Mainnet -> 0.20 (proven team, standard allocation)
        - Testnet -> 0.25 (moderate team allocation)
        - Ideation -> 0.30 (early stage, higher team%)
        - No URL (anonymous) -> 0.35 (higher risk, higher allocation)
    """
    if not project.url:
        # Anonymous team might take more
        return 0.35

    if project.stage == "mainnet":
        return 0.20
    elif project.stage == "testnet":
        return 0.25
    else:  # ideation or unknown
        return 0.30


def infer_unlock_pressure(vc_share: float, team_share: float) -> str:
    """Infer unlock pressure from VC/team allocation.

    Args:
        vc_share: VC share (0.0-1.0)
        team_share: Team share (0.0-1.0)

    Returns:
        Unlock pressure (low/medium/high)

    Logic:
        - Combined allocation < 0.35 -> low pressure
        - 0.35 <= combined <= 0.55 -> medium pressure
        - Combined > 0.55 -> high pressure
    """
    combined = vc_share + team_share

    if combined < 0.35:
        return "low"
    elif combined <= 0.55:
        return "medium"
    else:
        return "high"


def calculate_unlock_penalty(unlock_pressure: str) -> float:
    """Calculate unlock penalty from pressure level.

    Args:
        unlock_pressure: Unlock pressure (low/medium/high)

    Returns:
        Unlock penalty (0.0-1.0)

    Mapping (DATA_SCORING_DICT.md §5.7.1):
        low -> 0.15
        medium -> 0.35
        high -> 0.65
    """
    return UNLOCK_PENALTY_MAP.get(unlock_pressure, DEFAULT_UNLOCK_PENALTY)


class TokenomicsAgent(BaseAgent):
    """Tokenomics Agent - Token economics analysis.

    MVP: Uses heuristics from project stage and signals
    V2: Adds real tokenomics data from documentation and on-chain sources
    """

    def __init__(self):
        super().__init__("tokenomics")

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute tokenomics analysis.

        Args:
            state: Current pipeline state

        Returns:
            Updated state with tokenomics result
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Estimate VC and team shares
            vc_share = estimate_vc_share(state.project)
            team_share = estimate_team_share(state.project)

            # Infer unlock pressure
            unlock_pressure = infer_unlock_pressure(vc_share, team_share)

            # Calculate unlock penalty
            unlock_penalty = calculate_unlock_penalty(unlock_pressure)

            # Create result
            result = TokenomicsResult(
                vc_share=vc_share,
                team_share=team_share,
                unlock_penalty=unlock_penalty,
            )

            # Update state
            state.tokenomics = result

            self.logger.info(
                "tokenomics.completed",
                project_id=state.project.id,
                vc_share=round(vc_share, 2),
                team_share=round(team_share, 2),
                unlock_pressure=unlock_pressure,
                unlock_penalty=round(unlock_penalty, 2),
            )

        except Exception as e:
            error = AgentError(
                agent_name=self.name,
                kind="tokenomics_error",
                message=str(e),
                project_id=state.project.id
            )
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state


if __name__ == "__main__":
    # Test tokenomics agent
    import asyncio
    from app.agents.base import AgentContext, RawProject

    async def test():
        print("=== Testing Tokenomics Agent ===\n")

        # Test cases
        test_cases = [
            # Good tokenomics: Mainnet with funding
            RawProject(
                id="test-1",
                name="GoodTokenomics",
                sector="L2",
                stage="mainnet",
                recent_funding=True,
                url="https://good.xyz",
                source="seed"
            ),
            # Medium tokenomics: Testnet with funding
            RawProject(
                id="test-2",
                name="MediumTokenomics",
                sector="Restaking",
                stage="testnet",
                recent_funding=True,
                url="https://medium.xyz",
                source="seed"
            ),
            # High risk: Ideation with funding, no URL
            RawProject(
                id="test-3",
                name="HighRiskTokenomics",
                sector="DeFi",
                stage="ideation",
                recent_funding=True,
                url=None,
                source="seed"
            ),
            # Low allocation: No funding signals
            RawProject(
                id="test-4",
                name="LowAllocation",
                sector="Gaming",
                stage="testnet",
                recent_funding=False,
                url="https://low.xyz",
                source="seed"
            ),
        ]

        agent = TokenomicsAgent()

        for project in test_cases:
            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            result_state = await agent.run(state)

            if result_state.tokenomics:
                t = result_state.tokenomics
                combined = t.vc_share + t.team_share
                unlock_pressure = infer_unlock_pressure(t.vc_share, t.team_share)

                print(f"[OK] {project.name} ({project.stage})")
                print(f"  VC Share: {t.vc_share:.2f}")
                print(f"  Team Share: {t.team_share:.2f}")
                print(f"  Combined: {combined:.2f}")
                print(f"  Unlock Pressure: {unlock_pressure}")
                print(f"  Unlock Penalty: {t.unlock_penalty:.2f}")
                print()

        print("\n=== Testing Calculation Functions ===\n")

        # Test unlock pressure inference
        test_pressures = [
            (0.15, 0.15, "low", "Low combined"),
            (0.20, 0.20, "medium", "Medium combined"),
            (0.30, 0.30, "high", "High combined"),
            (0.25, 0.25, "medium", "Boundary medium"),
        ]

        for vc, team, expected, desc in test_pressures:
            pressure = infer_unlock_pressure(vc, team)
            penalty = calculate_unlock_penalty(pressure)
            print(f"[OK] {desc}")
            print(f"  VC: {vc:.2f}, Team: {team:.2f}")
            print(f"  Pressure: {pressure} (expected {expected})")
            print(f"  Penalty: {penalty:.2f}")
            print()

        print("\n=== Testing Unlock Penalty Mapping ===\n")

        for pressure, expected_penalty in UNLOCK_PENALTY_MAP.items():
            penalty = calculate_unlock_penalty(pressure)
            print(f"[OK] {pressure} -> {penalty:.2f} (expected {expected_penalty})")

        print("\n[OK] All tests completed!")

    asyncio.run(test())
