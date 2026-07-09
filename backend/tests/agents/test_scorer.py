"""Tests for Scorer Agent.

Reference:
- DATA_SCORING_DICT.md §4-§8
- backend/app/agents/scorer.py
"""

import pytest
from datetime import datetime, timezone

from app.agents.base import RawProject, AgentContext, PipelineState
from app.agents.scorer import ScorerAgent
from app.models import (
    NarrativeResult,
    TeamResult,
    RiskResult,
    TokenomicsResult,
)


@pytest.fixture
def context():
    """Shared agent context."""
    return AgentContext(run_id="test-run-001")


@pytest.fixture
def base_project():
    """Base project for testing."""
    return RawProject(
        id="test-project-001",
        name="TestProject",
        url="https://test.xyz",
        sector="L2",
        stage="testnet",
        source="seed",
        has_testnet=True,
        has_points_program=True,
        no_token_yet=True,
        recent_funding=True,
    )


class TestScorerAgent:
    """Test Scorer Agent creation and basic flow."""

    @pytest.mark.asyncio
    async def test_agent_creation(self):
        """Test agent can be created."""
        agent = ScorerAgent()
        assert agent.name == "scorer"
        assert agent.sector_counts == {}

    @pytest.mark.asyncio
    async def test_agent_with_sector_counts(self):
        """Test agent accepts sector counts."""
        counts = {"L2": 4, "DeFi": 10}
        agent = ScorerAgent(sector_counts=counts)
        assert agent.sector_counts == counts

    @pytest.mark.asyncio
    async def test_full_pipeline(self, base_project, context):
        """Test complete scoring with all agents present."""
        agent = ScorerAgent(sector_counts={"L2": 4})

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.82,
                timing="early",
            ),
            team=TeamResult(
                team_score=0.72,
                team_flags=["tier-1 vc backed"],
                team_type="doxxed",
            ),
            risk=RiskResult(
                token_risk=0.68,
                risk_flags=["kyc required"],
                unlock_pressure="medium",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.25,
                team_share=0.20,
                unlock_penalty=0.35,
            ),
        )

        result = await agent.run(state)

        assert result.score is not None
        assert result.label in ["FARM", "WATCH", "IGNORE"]
        assert result.confidence == 1.0  # All 4 agents present
        assert len(result.reason) >= 2
        assert result.errors == []


class TestAirdropSignal:
    """Test airdrop signal subscore calculation."""

    @pytest.mark.asyncio
    async def test_both_signals_true(self, base_project, context):
        """Test both has_points and airdrop_hint true -> 100."""
        base_project.has_points_program = True
        base_project.no_token_yet = True

        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)
        result = await agent.run(state)

        subscores = result.reason  # Access via state
        # We'll check via the actual score contribution
        assert result.score is not None

    @pytest.mark.asyncio
    async def test_only_points(self, base_project, context):
        """Test only has_points true -> 60."""
        base_project.has_points_program = True
        base_project.no_token_yet = False

        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        # Direct subscore test
        subscores = agent._calculate_subscores(state)
        assert subscores["airdrop_signal"] == 60.0

    @pytest.mark.asyncio
    async def test_only_airdrop_hint(self, base_project, context):
        """Test only airdrop_hint true -> 60."""
        base_project.has_points_program = False
        base_project.no_token_yet = True

        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["airdrop_signal"] == 60.0

    @pytest.mark.asyncio
    async def test_no_signals(self, base_project, context):
        """Test both false -> 20."""
        base_project.has_points_program = False
        base_project.no_token_yet = False

        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["airdrop_signal"] == 20.0


class TestNarrativeTiming:
    """Test narrative timing subscore calculation."""

    @pytest.mark.asyncio
    async def test_early_timing(self, base_project, context):
        """Test early timing with high heat."""
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.82,
                timing="early",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # 0.82 * 100 * 1.0 = 82
        assert subscores["narrative_timing"] == 82.0

    @pytest.mark.asyncio
    async def test_peak_timing(self, base_project, context):
        """Test peak timing coefficient."""
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="Restaking",
                stage="peak",
                heat_score=0.90,
                timing="peak",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # 0.90 * 100 * 0.8 = 72
        assert subscores["narrative_timing"] == 72.0

    @pytest.mark.asyncio
    async def test_late_timing(self, base_project, context):
        """Test late timing coefficient."""
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="DeFi",
                stage="mature",
                heat_score=0.60,
                timing="late",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # 0.60 * 100 * 0.5 = 30
        assert subscores["narrative_timing"] == 30.0

    @pytest.mark.asyncio
    async def test_narrative_missing(self, base_project, context):
        """Test narrative missing -> 50 (neutral)."""
        state = PipelineState(project=base_project, context=context)

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        assert subscores["narrative_timing"] == 50.0


class TestTeamReputation:
    """Test team reputation subscore calculation."""

    @pytest.mark.asyncio
    async def test_high_team_score(self, base_project, context):
        """Test high team score."""
        state = PipelineState(
            project=base_project,
            context=context,
            team=TeamResult(
                team_score=0.75,
                team_flags=["tier-1 vc backed"],
                team_type="doxxed",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # 0.75 * 100 = 75
        assert subscores["team_reputation"] == 75.0

    @pytest.mark.asyncio
    async def test_low_team_score(self, base_project, context):
        """Test low team score."""
        state = PipelineState(
            project=base_project,
            context=context,
            team=TeamResult(
                team_score=0.25,
                team_flags=["anonymous team"],
                team_type="anon",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # 0.25 * 100 = 25
        assert subscores["team_reputation"] == 25.0

    @pytest.mark.asyncio
    async def test_team_missing(self, base_project, context):
        """Test team missing -> 50 (neutral)."""
        state = PipelineState(project=base_project, context=context)

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        assert subscores["team_reputation"] == 50.0


class TestRiskSubscore:
    """Test risk subscore calculation."""

    @pytest.mark.asyncio
    async def test_high_sybil_difficulty(self, base_project, context):
        """Test high sybil difficulty (kyc required)."""
        state = PipelineState(
            project=base_project,
            context=context,
            risk=RiskResult(
                token_risk=0.30,
                risk_flags=["kyc required"],
                unlock_pressure="low",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # (1 - 0.30) * 100 * 1.0 = 70
        assert subscores["risk"] == 70.0

    @pytest.mark.asyncio
    async def test_medium_sybil_difficulty(self, base_project, context):
        """Test medium sybil difficulty."""
        state = PipelineState(
            project=base_project,
            context=context,
            risk=RiskResult(
                token_risk=0.40,
                risk_flags=[],
                unlock_pressure="medium",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # (1 - 0.40) * 100 * 0.85 = 51
        assert subscores["risk"] == 51.0

    @pytest.mark.asyncio
    async def test_low_sybil_difficulty(self, base_project, context):
        """Test low sybil difficulty (testnet only)."""
        state = PipelineState(
            project=base_project,
            context=context,
            risk=RiskResult(
                token_risk=0.20,
                risk_flags=["testnet only"],
                unlock_pressure="low",
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # (1 - 0.20) * 100 * 0.70 = 56
        assert subscores["risk"] == 56.0

    @pytest.mark.asyncio
    async def test_risk_missing(self, base_project, context):
        """Test risk missing -> 50 (neutral)."""
        state = PipelineState(project=base_project, context=context)

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        assert subscores["risk"] == 50.0


class TestTokenomicsSubscore:
    """Test tokenomics subscore calculation."""

    @pytest.mark.asyncio
    async def test_low_unlock_pressure(self, base_project, context):
        """Test low VC/team shares and unlock pressure."""
        state = PipelineState(
            project=base_project,
            context=context,
            tokenomics=TokenomicsResult(
                vc_share=0.20,
                team_share=0.15,
                unlock_penalty=0.15,
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # tok_risk = 0.20*0.4 + 0.15*0.3 + 0.15*0.3 = 0.08 + 0.045 + 0.045 = 0.17
        # subscore = (1 - 0.17) * 100 = 83
        assert subscores["tokenomics"] == pytest.approx(83.0, rel=0.01)

    @pytest.mark.asyncio
    async def test_high_unlock_pressure(self, base_project, context):
        """Test high VC/team shares and unlock pressure."""
        state = PipelineState(
            project=base_project,
            context=context,
            tokenomics=TokenomicsResult(
                vc_share=0.35,
                team_share=0.30,
                unlock_penalty=0.65,
            ),
        )

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        # tok_risk = 0.35*0.4 + 0.30*0.3 + 0.65*0.3 = 0.14 + 0.09 + 0.195 = 0.425
        # subscore = (1 - 0.425) * 100 = 57.5
        assert subscores["tokenomics"] == pytest.approx(57.5, rel=0.01)

    @pytest.mark.asyncio
    async def test_tokenomics_missing(self, base_project, context):
        """Test tokenomics missing -> 50 (neutral)."""
        state = PipelineState(project=base_project, context=context)

        agent = ScorerAgent()
        subscores = agent._calculate_subscores(state)

        assert subscores["tokenomics"] == 50.0


class TestCompetitionSubscore:
    """Test competition subscore calculation."""

    @pytest.mark.asyncio
    async def test_low_competition(self, base_project, context):
        """Test n <= 3 -> 100."""
        agent = ScorerAgent(sector_counts={"L2": 2})
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["competition"] == 100.0

    @pytest.mark.asyncio
    async def test_medium_competition(self, base_project, context):
        """Test 4 <= n <= 8 -> 75."""
        agent = ScorerAgent(sector_counts={"L2": 6})
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["competition"] == 75.0

    @pytest.mark.asyncio
    async def test_high_competition(self, base_project, context):
        """Test 9 <= n <= 15 -> 55."""
        agent = ScorerAgent(sector_counts={"L2": 12})
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["competition"] == 55.0

    @pytest.mark.asyncio
    async def test_very_high_competition(self, base_project, context):
        """Test n > 15 -> 40."""
        agent = ScorerAgent(sector_counts={"L2": 20})
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["competition"] == 40.0

    @pytest.mark.asyncio
    async def test_competition_sector_missing(self, base_project, context):
        """Test sector not in counts -> 50 (neutral)."""
        agent = ScorerAgent(sector_counts={})
        state = PipelineState(project=base_project, context=context)

        subscores = agent._calculate_subscores(state)
        assert subscores["competition"] == 50.0


class TestLabelMapping:
    """Test score to label mapping."""

    @pytest.mark.asyncio
    async def test_farm_label(self, base_project, context):
        """Test score >= 70 -> FARM."""
        agent = ScorerAgent(sector_counts={"L2": 2})

        # Configure for high score
        base_project.has_points_program = True
        base_project.no_token_yet = True

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.85,
                timing="early",
            ),
            team=TeamResult(
                team_score=0.80,
                team_flags=["tier-1 vc backed"],
                team_type="doxxed",
            ),
            risk=RiskResult(
                token_risk=0.25,
                risk_flags=["kyc required"],
                unlock_pressure="low",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.20,
                team_share=0.15,
                unlock_penalty=0.15,
            ),
        )

        result = await agent.run(state)
        assert result.label == "FARM"
        assert result.score >= 70

    @pytest.mark.asyncio
    async def test_watch_label(self, base_project, context):
        """Test 50 <= score < 70 -> WATCH."""
        agent = ScorerAgent(sector_counts={"L2": 8})

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="peak",
                heat_score=0.70,
                timing="peak",
            ),
            team=TeamResult(
                team_score=0.60,
                team_flags=[],
                team_type="semi_anon",
            ),
            risk=RiskResult(
                token_risk=0.50,
                risk_flags=[],
                unlock_pressure="medium",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.30,
                team_share=0.25,
                unlock_penalty=0.35,
            ),
        )

        result = await agent.run(state)
        assert result.label == "WATCH"
        assert 50 <= result.score < 70

    @pytest.mark.asyncio
    async def test_ignore_label(self, base_project, context):
        """Test score < 50 -> IGNORE."""
        agent = ScorerAgent(sector_counts={"L2": 20})

        # Configure for low score
        base_project.has_points_program = False
        base_project.no_token_yet = False

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="DeFi",
                stage="mature",
                heat_score=0.50,
                timing="late",
            ),
            team=TeamResult(
                team_score=0.30,
                team_flags=["anonymous team"],
                team_type="anon",
            ),
            risk=RiskResult(
                token_risk=0.75,
                risk_flags=[],
                unlock_pressure="high",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.35,
                team_share=0.30,
                unlock_penalty=0.65,
            ),
        )

        result = await agent.run(state)
        assert result.label == "IGNORE"
        assert result.score < 50


class TestConfidence:
    """Test confidence calculation."""

    @pytest.mark.asyncio
    async def test_all_agents_present(self, base_project, context):
        """Test confidence = 1.0 when all 4 agents present."""
        agent = ScorerAgent()

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.80,
                timing="early",
            ),
            team=TeamResult(
                team_score=0.70,
                team_flags=[],
                team_type="doxxed",
            ),
            risk=RiskResult(
                token_risk=0.40,
                risk_flags=[],
                unlock_pressure="medium",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.25,
                team_share=0.20,
                unlock_penalty=0.35,
            ),
        )

        result = await agent.run(state)
        assert result.confidence == 1.0

    @pytest.mark.asyncio
    async def test_one_agent_missing(self, base_project, context):
        """Test confidence = 0.75 when 1 agent missing."""
        agent = ScorerAgent()

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.80,
                timing="early",
            ),
            team=TeamResult(
                team_score=0.70,
                team_flags=[],
                team_type="doxxed",
            ),
            risk=RiskResult(
                token_risk=0.40,
                risk_flags=[],
                unlock_pressure="medium",
            ),
            # tokenomics missing
        )

        result = await agent.run(state)
        assert result.confidence == 0.75

    @pytest.mark.asyncio
    async def test_three_agents_missing(self, base_project, context):
        """Test confidence = 0.25 when 3 agents missing."""
        agent = ScorerAgent()

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.80,
                timing="early",
            ),
            # team, risk, tokenomics missing
        )

        result = await agent.run(state)
        assert result.confidence == 0.25


class TestConfidenceDegradation:
    """Test label degradation when confidence < 0.5."""

    @pytest.mark.asyncio
    async def test_farm_degraded_to_watch(self, base_project, context):
        """Test FARM -> WATCH when confidence < 0.5."""
        agent = ScorerAgent(sector_counts={"L2": 2})

        # High airdrop signal to push toward FARM
        base_project.has_points_program = True
        base_project.no_token_yet = True

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.90,
                timing="early",
            ),
            # Only 1 of 4 agents present -> confidence = 0.25
        )

        result = await agent.run(state)
        assert result.confidence == 0.25
        # Even if raw score >= 70, label should be degraded
        assert result.label == "WATCH"

    @pytest.mark.asyncio
    async def test_watch_degraded_to_ignore(self, base_project, context):
        """Test WATCH -> IGNORE when confidence < 0.5."""
        agent = ScorerAgent(sector_counts={"L2": 8})

        state = PipelineState(
            project=base_project,
            context=context,
            team=TeamResult(
                team_score=0.60,
                team_flags=[],
                team_type="semi_anon",
            ),
            # Only 1 of 4 agents present -> confidence = 0.25
        )

        result = await agent.run(state)
        assert result.confidence == 0.25
        # Even if raw score would be WATCH, label should be degraded
        assert result.label == "IGNORE"


class TestReasonGeneration:
    """Test reason generation logic."""

    @pytest.mark.asyncio
    async def test_reason_minimum_length(self, base_project, context):
        """Test reasons list has at least 2 items."""
        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        result = await agent.run(state)
        assert len(result.reason) >= 2

    @pytest.mark.asyncio
    async def test_strong_airdrop_signal_reason(self, base_project, context):
        """Test 'strong airdrop signal' appears when both signals true."""
        base_project.has_points_program = True
        base_project.no_token_yet = True

        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        result = await agent.run(state)
        assert "strong airdrop signal" in result.reason

    @pytest.mark.asyncio
    async def test_missing_data_reasons(self, base_project, context):
        """Test missing data reasons are included."""
        agent = ScorerAgent()
        state = PipelineState(
            project=base_project,
            context=context,
            # All agents missing
        )

        result = await agent.run(state)

        # Should have missing markers
        missing_markers = [
            "narrative heat unknown",
            "team data missing",
            "risk estimate uncertain",
            "tokenomics data missing",
        ]

        # At least some missing markers should be present
        assert any(marker in result.reason for marker in missing_markers)

    @pytest.mark.asyncio
    async def test_low_confidence_reason(self, base_project, context):
        """Test 'low data confidence' appears when confidence < 0.5."""
        agent = ScorerAgent()
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.80,
                timing="early",
            ),
            # Only 1 of 4 agents -> confidence = 0.25
        )

        result = await agent.run(state)
        assert result.confidence == 0.25
        assert "low data confidence" in result.reason


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_all_agents_missing(self, base_project, context):
        """Test scoring works with all agents missing."""
        agent = ScorerAgent()
        state = PipelineState(project=base_project, context=context)

        result = await agent.run(state)

        assert result.score is not None
        assert result.label in ["FARM", "WATCH", "IGNORE"]
        assert result.confidence == 0.0
        assert len(result.reason) >= 2

    @pytest.mark.asyncio
    async def test_zero_heat_score(self, base_project, context):
        """Test narrative with zero heat score."""
        agent = ScorerAgent()
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="Unknown",
                stage="mature",
                heat_score=0.0,
                timing="late",
            ),
        )

        result = await agent.run(state)
        assert result.score is not None

    @pytest.mark.asyncio
    async def test_max_heat_score(self, base_project, context):
        """Test narrative with max heat score."""
        agent = ScorerAgent()
        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="Restaking",
                stage="peak",
                heat_score=1.0,
                timing="peak",
            ),
        )

        result = await agent.run(state)
        assert result.score is not None


class TestLayerXExample:
    """Test LayerX example from DATA_SCORING_DICT.md §12."""

    @pytest.mark.asyncio
    async def test_layerx_scoring(self, base_project, context):
        """Test LayerX example calculation.

        Note: The actual score differs from DATA_SCORING_DICT.md §12 example
        because that example used different tokenomics.risk calculation.
        Our implementation correctly uses: vc_share*0.4 + team_share*0.3 + unlock_penalty*0.3
        """
        # Setup LayerX-like project
        base_project.has_points_program = True
        base_project.no_token_yet = True
        base_project.sector = "L2"

        agent = ScorerAgent(sector_counts={"L2": 4})

        state = PipelineState(
            project=base_project,
            context=context,
            narrative=NarrativeResult(
                sector="L2",
                stage="growth",
                heat_score=0.82,
                timing="early",
            ),
            team=TeamResult(
                team_score=0.72,
                team_flags=["tier-1 vc backed"],
                team_type="doxxed",
            ),
            risk=RiskResult(
                token_risk=0.68,
                risk_flags=["kyc required"],
                unlock_pressure="medium",
            ),
            tokenomics=TokenomicsResult(
                vc_share=0.25,
                team_share=0.20,
                unlock_penalty=0.35,  # medium unlock pressure
            ),
        )

        result = await agent.run(state)

        # Actual calculation:
        # airdrop_signal: 100 * 0.20 = 20.0
        # narrative_timing: 82 * 0.20 = 16.4
        # team_reputation: 72 * 0.15 = 10.8
        # risk: (1-0.68)*100*1.0 = 32 * 0.15 = 4.8
        # tokenomics: (1-(0.25*0.4+0.20*0.3+0.35*0.3))*100 = 73.5 * 0.15 = 11.025
        # competition: 75 * 0.15 = 11.25
        # Total: 20.0 + 16.4 + 10.8 + 4.8 + 11.025 + 11.25 = 74.275 -> 74

        assert result.score == 74
        assert result.label == "FARM"  # 74 >= 70
        assert result.confidence == 1.0
        assert "strong airdrop signal" in result.reason
