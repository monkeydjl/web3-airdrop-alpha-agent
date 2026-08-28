"""Team Agent - Team reputation analysis.

Analyzes team credibility and flags team-related risks.
Produces team score, risk level, and flags based on available signals.

Reference:
- ENGINEERING_ROADMAP.md §6.4 Team Reputation
- DATA_SCORING_DICT.md §3.2 TeamResult
- DATA_SCORING_DICT.md §5.7.3 Team multi-flag logic
"""

import time

import structlog

from app.agents.base import AgentError, BaseAgent, PipelineState
from app.models import TeamResult

logger = structlog.get_logger(__name__)


# Team flag adjustment configuration
# Format: flag -> adjustment (added to base score)
FLAG_ADJUSTMENTS: dict[str, float] = {
    "anonymous team": -0.25,
    "previous failed project": -0.30,
    "wash-trading VC": -0.20,
    "tier-1 vc backed": +0.25,
    "reputable vc backed": +0.15,
    "recent funding": +0.08,
    "doxxed team": +0.20,
    "successful prior exit": +0.30,
}

# Base team score (neutral)
BASE_TEAM_SCORE = 0.5


def calculate_team_score(flags: list[str]) -> float:
    """Calculate team score from flags.

    Args:
        flags: List of team flags

    Returns:
        Team score (0.0-1.0)

    Algorithm:
        base = 0.5
        score = base + sum(adjustments[flag] for flag in flags)
        score = clamp(score, 0.0, 1.0)
    """
    score = BASE_TEAM_SCORE

    for flag in flags:
        adjustment = FLAG_ADJUSTMENTS.get(flag, 0.0)
        score += adjustment

    # Clamp to [0.0, 1.0]
    return max(0.0, min(1.0, score))


def score_to_risk_level(score: float) -> str:
    """Map team score to risk level.

    Args:
        score: Team score (0.0-1.0)

    Returns:
        Risk level (low/medium/high)

    Mapping:
        score < 0.4 -> high
        0.4 <= score <= 0.7 -> medium
        score > 0.7 -> low
    """
    if score < 0.4:
        return "high"
    elif score <= 0.7:
        return "medium"
    else:
        return "low"


def infer_team_flags(project: "RawProject") -> list[str]:
    """Infer team flags from project signals.

    MVP: Simple heuristics based on available signals
    V2: Add real data sources (team pages, social, funding rounds)

    Args:
        project: Raw project data

    Returns:
        List of team flags
    """
    flags = []

    # Funding quality (RootData / structured).
    # DATA_SCORING_DICT §196：`tier-1 vc backed` / `reputable vc backed` 由
    # funding_tier / funding_quality 这类**结构化证据**决定。
    # 此前有一条 `recent_funding and fq <= 0 -> tier-1` 的遗留分支，使仅凭描述
    # 文本推断出的融资信号（零结构化证据）拿到 +0.25，反而高于真实披露的 tier-3
    # 融资（+0.08），证据序颠倒；该分支已移除。
    fq = float(getattr(project, "funding_quality", 0) or 0)
    tier = str(getattr(project, "funding_tier", "unknown") or "unknown").lower()
    if tier == "tier1" or fq >= 0.65:
        flags.append("tier-1 vc backed")
    elif tier == "tier2" or fq >= 0.45:
        flags.append("reputable vc backed")
    elif project.recent_funding or fq >= 0.25:
        flags.append("recent funding")

    # Check stage (early stage = higher uncertainty)
    if project.stage == "ideation" or project.stage == "testnet":
        pass
    elif project.stage == "mainnet":
        flags.append("doxxed team")

    if not project.url and not project.recent_funding and fq < 0.2:
        flags.append("anonymous team")

    return flags


def infer_team_type(flags: list[str]) -> str:
    """Infer team type from flags.

    Args:
        flags: List of team flags

    Returns:
        Team type (doxxed/semi_anon/anon/unknown)

    Logic:
        - "doxxed team" flag -> doxxed
        - "anonymous team" flag -> anon
        - Has positive flags (VC/funding) but no doxxed flag -> semi_anon
        - Otherwise -> unknown
    """
    if "doxxed team" in flags:
        return "doxxed"
    elif "anonymous team" in flags:
        return "anon"
    elif any(f in flags for f in ["tier-1 vc backed", "reputable vc backed", "recent funding"]):
        return "semi_anon"
    else:
        return "unknown"


class TeamAgent(BaseAgent):
    """Team Agent - Team reputation analysis.

    MVP: Uses heuristics from project stage and signals
    V2: Adds real team data (social profiles, funding rounds, prior projects)
    """

    def __init__(self) -> None:
        super().__init__("team")

    async def run(self, state: PipelineState) -> PipelineState:
        """Execute team analysis.

        Args:
            state: Current pipeline state

        Returns:
            Updated state with team result
        """
        self._log_start(state)
        start_time = time.time()

        try:
            # Infer team flags from project
            flags = infer_team_flags(state.project)

            # Calculate team score
            team_score = calculate_team_score(flags)

            # Infer team type
            team_type = infer_team_type(flags)

            # Create result
            result = TeamResult(
                team_score=team_score,
                team_flags=flags,
                team_type=team_type,
            )

            # Update state
            state.team = result

            self.logger.info(
                "team.completed",
                project_id=state.project.id,
                team_score=round(team_score, 2),
                team_type=team_type,
                flags=flags,
            )

        except Exception as e:
            error = AgentError(agent_name=self.name, kind="team_error", message=str(e), project_id=state.project.id)
            state.add_error(error)

        duration_ms = (time.time() - start_time) * 1000
        self._log_complete(state, duration_ms)

        return state


if __name__ == "__main__":
    # Test team agent
    import asyncio

    from app.agents.base import AgentContext, RawProject

    async def test() -> None:
        print("=== Testing Team Agent ===\n")

        # Test cases
        test_projects = [
            # High reputation: VC backed + mainnet
            RawProject(
                id="test-1",
                name="EigenLayer",
                sector="Restaking",
                stage="mainnet",
                recent_funding=True,
                url="https://eigenlayer.xyz",
                source="seed",
            ),
            # Medium: Testnet with funding
            RawProject(
                id="test-2",
                name="LayerX",
                sector="L2",
                stage="testnet",
                recent_funding=True,
                url="https://layerx.xyz",
                source="seed",
            ),
            # Low: Anonymous team, no signals
            RawProject(
                id="test-3",
                name="UnknownProject",
                sector="DeFi",
                stage="ideation",
                recent_funding=False,
                url=None,
                source="seed",
            ),
            # Neutral: Testnet, no special signals
            RawProject(
                id="test-4",
                name="RegularProject",
                sector="Gaming",
                stage="testnet",
                recent_funding=False,
                url="https://regular.xyz",
                source="seed",
            ),
        ]

        agent = TeamAgent()

        for project in test_projects:
            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            result_state = await agent.run(state)

            if result_state.team:
                t = result_state.team
                print(f"[OK] {project.name} ({project.stage})")
                print(f"  Score: {t.team_score:.2f}")
                print(f"  Type: {t.team_type}")
                print(f"  Flags: {t.team_flags}")
                print(f"  Risk: {score_to_risk_level(t.team_score)}")
                print()

        print("\n=== Testing Flag Calculations ===\n")

        # Test flag combinations
        test_flags = [
            ([], "No flags"),
            (["tier-1 vc backed"], "VC backed"),
            (["anonymous team"], "Anonymous"),
            (["doxxed team", "tier-1 vc backed"], "Doxxed + VC"),
            (["anonymous team", "previous failed project"], "Anonymous + Failed"),
            (["doxxed team", "successful prior exit"], "Doxxed + Success"),
        ]

        for flags, description in test_flags:
            score = calculate_team_score(flags)
            risk = score_to_risk_level(score)
            team_type = infer_team_type(flags)
            print(f"[OK] {description}")
            print(f"  Flags: {flags}")
            print(f"  Score: {score:.2f}")
            print(f"  Risk: {risk}")
            print(f"  Type: {team_type}")
            print()

        print("[OK] All tests completed!")

    asyncio.run(test())
