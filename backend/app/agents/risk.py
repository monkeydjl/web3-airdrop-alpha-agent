"""Risk Agent - Risk assessment and token structure analysis.

Analyzes project risks including token structure, sybil difficulty, and farming costs.
Produces token_risk score, risk flags, and unlock pressure assessment.

Reference:
- ENGINEERING_ROADMAP.md §6.5 Risk Assessment
- DATA_SCORING_DICT.md §3.3 RiskResult
- DATA_SCORING_DICT.md §5.7.2 Risk token_risk heuristic
"""

import time

import structlog

from app.agents.airdrop_signal import airdrop_signal_subscore
from app.agents.base import AgentError, BaseAgent, PipelineState
from app.models import RiskResult

logger = structlog.get_logger(__name__)


# Stage risk factor configuration
STAGE_RISK_FACTOR: dict[str, float] = {
    "mainnet": 0.15,  # Proven execution, lower risk
    "testnet": 0.35,  # Testing phase, medium risk
    "ideation": 0.55,  # No product yet, higher risk
}

# Default stage factor for unknown stages
DEFAULT_STAGE_FACTOR = 0.40


def calculate_airdrop_signal_subscore(project: "RawProject") -> float:
    """Calculate airdrop signal subscore.

    保留此函数名以兼容既有调用方，实现委托给 `app.agents.airdrop_signal` 的
    唯一实现。此前这里是 Scorer 那份阶梯的复制品，且漏掉了 v1.4 的
    funding_quality 分支，导致 token_risk 基于一份过时的空投子分计算。
    """
    return airdrop_signal_subscore(project)


def calculate_token_risk(project: "RawProject", tokenomics_risk: float | None = None) -> float:
    """Calculate token risk score using heuristic.

    MVP heuristic (DATA_SCORING_DICT.md §5.7.2):
        token_risk = 0.6 × tokenomics.risk
                   + 0.2 × (1 - airdrop_signal_subscore / 100)
                   + 0.2 × stage_factor

        stage_factor = {mainnet: 0.15, testnet: 0.35, ideation: 0.55}

    Args:
        project: Raw project data
        tokenomics_risk: Tokenomics risk (0-1), None if unavailable

    Returns:
        Token risk score (0.0-1.0, higher = more risky)
    """
    # Get tokenomics risk (default 0.5 if missing)
    if tokenomics_risk is None:
        tokenomics_risk = 0.5

    # Calculate airdrop signal subscore
    airdrop_subscore = calculate_airdrop_signal_subscore(project)

    # Get stage factor
    stage = project.stage or "testnet"
    stage_factor = STAGE_RISK_FACTOR.get(stage, DEFAULT_STAGE_FACTOR)

    # Calculate token risk
    token_risk = 0.6 * tokenomics_risk + 0.2 * (1 - airdrop_subscore / 100) + 0.2 * stage_factor

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, token_risk))


def assess_sybil_difficulty(project: "RawProject") -> str:
    """Assess sybil attack difficulty.

    Args:
        project: Raw project data

    Returns:
        Sybil difficulty (low/medium/high)

    Heuristics:
        - Testnet with points program -> high (requires real activity)
        - Mainnet -> high (on-chain verification)
        - Has testnet signal -> medium
        - Ideation or no signals -> low (easy to farm)
    """
    if project.stage == "mainnet":
        return "high"

    if project.has_testnet and project.has_points_program:
        return "high"

    if project.has_testnet or project.stage == "testnet":
        return "medium"

    return "low"


def assess_farming_cost(project: "RawProject") -> str:
    """Assess farming cost (gas + time).

    Args:
        project: Raw project data

    Returns:
        Farming cost (low/medium/high)

    Heuristics:
        - Mainnet -> high (gas costs)
        - Testnet with points -> medium (time investment)
        - Ideation or simple -> low (minimal effort)
    """
    if project.stage == "mainnet":
        return "high"

    if project.has_points_program or project.stage == "testnet":
        return "medium"

    return "low"


def infer_unlock_pressure(token_risk: float) -> str:
    """Infer unlock pressure from token risk.

    Args:
        token_risk: Token risk score (0.0-1.0)

    Returns:
        Unlock pressure (low/medium/high)

    Mapping:
        token_risk < 0.35 -> low
        0.35 <= token_risk <= 0.65 -> medium
        token_risk > 0.65 -> high
    """
    if token_risk < 0.35:
        return "low"
    elif token_risk <= 0.65:
        return "medium"
    else:
        return "high"


def generate_risk_flags(
    project: "RawProject", token_risk: float, sybil_difficulty: str, tokenomics_missing: bool
) -> list[str]:
    """Generate risk flags based on analysis.

    Args:
        project: Raw project data
        token_risk: Token risk score
        sybil_difficulty: Sybil difficulty assessment
        tokenomics_missing: Whether tokenomics data is missing

    Returns:
        List of risk flags
    """
    flags = []

    # Token structure risk
    if token_risk > 0.65:
        flags.append("high token structure risk")

    # Sybil farming risk
    if sybil_difficulty == "low":
        flags.append("easy to sybil farm")

    # Missing data
    if tokenomics_missing:
        flags.append("risk estimate uncertain")

    # Stage-specific risks
    if project.stage == "ideation":
        flags.append("no product yet")

    # No airdrop signals
    if not project.has_points_program and not project.no_token_yet:
        flags.append("weak airdrop signals")

    return flags


class RiskAgent(BaseAgent):
    """Risk Agent - Risk assessment and token structure analysis.

    MVP: Uses heuristics from project stage and signals
    V2: Adds real tokenomics data and on-chain metrics
    """

    def __init__(self):
        super().__init__("risk")

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute risk analysis.

        Args:
            state: Current pipeline state

        Returns:
            Updated state with risk result
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Get tokenomics risk if available
            tokenomics_risk = None
            tokenomics_missing = False

            if state.tokenomics:
                # DATA_SCORING_DICT §5.7.2: token_risk = 0.6 × tokenomics.risk，
                # 其中 tokenomics.risk 是 vc/team/unlock 三项加权，而非 unlock 单项。
                tokenomics_risk = state.tokenomics.risk
            else:
                tokenomics_missing = True

            # Calculate token risk
            token_risk = calculate_token_risk(state.project, tokenomics_risk)

            # Assess sybil difficulty
            sybil_difficulty = assess_sybil_difficulty(state.project)

            # Assess farming cost (not in RiskResult but useful for logging)
            farming_cost = assess_farming_cost(state.project)

            # Infer unlock pressure
            unlock_pressure = infer_unlock_pressure(token_risk)

            # Generate risk flags
            risk_flags = generate_risk_flags(state.project, token_risk, sybil_difficulty, tokenomics_missing)

            # Create result（sybil_difficulty 此前只进日志，Scorer 拿不到只能猜字符串）
            result = RiskResult(
                token_risk=token_risk,
                risk_flags=risk_flags,
                unlock_pressure=unlock_pressure,
                sybil_difficulty=sybil_difficulty,
            )

            # Update state
            state.risk = result

            self.logger.info(
                "risk.completed",
                project_id=state.project.id,
                token_risk=round(token_risk, 2),
                sybil_difficulty=sybil_difficulty,
                farming_cost=farming_cost,
                unlock_pressure=unlock_pressure,
                flags=risk_flags,
            )

        except Exception as e:
            error = AgentError(agent_name=self.name, kind="risk_error", message=str(e), project_id=state.project.id)
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state


if __name__ == "__main__":
    # Test risk agent
    import asyncio
    from typing import Any

    from app.agents.base import AgentContext, RawProject
    from app.models import TokenomicsResult

    async def test():
        print("=== Testing Risk Agent ===\n")

        # Test cases
        test_cases: list[dict[str, Any]] = [
            # High risk: Ideation, no signals
            {
                "name": "HighRisk",
                "project": RawProject(
                    id="test-1",
                    name="HighRisk",
                    sector="DeFi",
                    stage="ideation",
                    has_testnet=False,
                    has_points_program=False,
                    no_token_yet=False,
                    url=None,
                    source="seed",
                ),
                "tokenomics": None,
            },
            # Medium risk: Testnet with points
            {
                "name": "MediumRisk",
                "project": RawProject(
                    id="test-2",
                    name="MediumRisk",
                    sector="L2",
                    stage="testnet",
                    has_testnet=True,
                    has_points_program=True,
                    no_token_yet=True,
                    url="https://medium.xyz",
                    source="seed",
                ),
                "tokenomics": TokenomicsResult(
                    vc_share=0.25,
                    team_share=0.20,
                    unlock_penalty=0.35,
                ),
            },
            # Low risk: Mainnet with good tokenomics
            {
                "name": "LowRisk",
                "project": RawProject(
                    id="test-3",
                    name="LowRisk",
                    sector="Restaking",
                    stage="mainnet",
                    has_testnet=True,
                    has_points_program=True,
                    no_token_yet=False,
                    url="https://low.xyz",
                    source="seed",
                ),
                "tokenomics": TokenomicsResult(
                    vc_share=0.15,
                    team_share=0.15,
                    unlock_penalty=0.20,
                ),
            },
        ]

        agent = RiskAgent()

        for test_case in test_cases:
            project = test_case["project"]
            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            # Add tokenomics if available
            if test_case["tokenomics"]:
                state.tokenomics = test_case["tokenomics"]

            result_state = await agent.run(state)

            if result_state.risk:
                r = result_state.risk
                print(f"[OK] {test_case['name']} ({project.stage})")
                print(f"  Token Risk: {r.token_risk:.2f}")
                print(f"  Unlock Pressure: {r.unlock_pressure}")
                print(f"  Flags: {r.risk_flags}")
                print()

        print("\n=== Testing Calculation Functions ===\n")

        # Test airdrop signal subscore
        test_signals = [
            (True, True, 100.0, "Points + Hint"),
            (True, False, 60.0, "Points only"),
            (False, True, 60.0, "Hint only"),
            (False, False, 20.0, "No signals"),
        ]

        for has_points, has_hint, expected, desc in test_signals:
            proj = RawProject(
                id="test", name="Test", sector="L2", has_points_program=has_points, no_token_yet=has_hint, source="seed"
            )
            score = calculate_airdrop_signal_subscore(proj)
            print(f"[OK] {desc}: {score:.0f} (expected {expected})")

        print("\n[OK] All tests completed!")

    asyncio.run(test())
