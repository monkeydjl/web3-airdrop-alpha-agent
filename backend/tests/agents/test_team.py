"""Unit tests for Team Agent.

Tests team reputation analysis, flag adjustments, and risk level mapping.

Reference:
- app/agents/team.py
- DATA_SCORING_DICT.md §3.2 TeamResult
- DATA_SCORING_DICT.md §5.7.3 Team multi-flag logic
"""

import pytest
from pydantic import ValidationError

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.team import (
    BASE_TEAM_SCORE,
    FLAG_ADJUSTMENTS,
    TeamAgent,
    calculate_team_score,
    infer_team_flags,
    infer_team_type,
    score_to_risk_level,
)


class TestTeamAgent:
    """Test TeamAgent class."""

    @pytest.mark.asyncio
    async def test_agent_creation(self):
        """Test agent creation and naming."""
        agent = TeamAgent()
        assert agent.name == "team"

    @pytest.mark.asyncio
    async def test_high_reputation_project(self):
        """Test project with high team reputation (VC + mainnet)."""
        project = RawProject(
            id="test-high-rep",
            name="EigenLayer",
            sector="Restaking",
            stage="mainnet",
            recent_funding=True,
            url="https://eigenlayer.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None
        assert result_state.team.team_score >= 0.7  # High score
        assert result_state.team.team_type == "doxxed"
        assert "recent funding" in result_state.team.team_flags  # §196: tier-1 需结构化融资证据
        assert "doxxed team" in result_state.team.team_flags
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_medium_reputation_project(self):
        """Test project with medium reputation (testnet + VC)."""
        project = RawProject(
            id="test-med-rep",
            name="LayerX",
            sector="L2",
            stage="testnet",
            recent_funding=True,
            url="https://layerx.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None
        assert 0.4 <= result_state.team.team_score <= 1.0
        assert result_state.team.team_type == "semi_anon"
        assert "recent funding" in result_state.team.team_flags  # §196: tier-1 需结构化融资证据
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_low_reputation_project(self):
        """Test project with low reputation (anon + no signals)."""
        project = RawProject(
            id="test-low-rep",
            name="UnknownProject",
            sector="DeFi",
            stage="ideation",
            recent_funding=False,
            url=None,
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None
        assert result_state.team.team_score < 0.4  # Low score
        assert result_state.team.team_type == "anon"
        assert "anonymous team" in result_state.team.team_flags
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_neutral_project(self):
        """Test project with neutral signals."""
        project = RawProject(
            id="test-neutral",
            name="RegularProject",
            sector="Gaming",
            stage="testnet",
            recent_funding=False,
            url="https://regular.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None
        assert result_state.team.team_score == BASE_TEAM_SCORE  # Neutral
        assert result_state.team.team_type == "unknown"
        assert len(result_state.team.team_flags) == 0
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_result_immutability(self):
        """Test that TeamResult is immutable."""
        project = RawProject(id="test-immutable", name="Test", sector="L2", stage="testnet", source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None

        # Try to modify - should raise FrozenInstanceError
        with pytest.raises(ValidationError):
            result_state.team.team_score = 0.99


class TestCalculateTeamScore:
    """Test calculate_team_score function."""

    def test_no_flags(self):
        """Test score with no flags (neutral)."""
        score = calculate_team_score([])
        assert score == BASE_TEAM_SCORE
        assert score == 0.5

    def test_single_positive_flag(self):
        """Test score with single positive flag."""
        score = calculate_team_score(["tier-1 vc backed"])
        assert score == BASE_TEAM_SCORE + FLAG_ADJUSTMENTS["tier-1 vc backed"]
        assert score == 0.75

    def test_single_negative_flag(self):
        """Test score with single negative flag."""
        score = calculate_team_score(["anonymous team"])
        assert score == BASE_TEAM_SCORE + FLAG_ADJUSTMENTS["anonymous team"]
        assert score == 0.25

    def test_multiple_positive_flags(self):
        """Test score with multiple positive flags."""
        score = calculate_team_score(["tier-1 vc backed", "doxxed team"])
        expected = BASE_TEAM_SCORE + FLAG_ADJUSTMENTS["tier-1 vc backed"] + FLAG_ADJUSTMENTS["doxxed team"]
        assert score == expected
        assert score == 0.95

    def test_multiple_negative_flags(self):
        """Test score with multiple negative flags."""
        score = calculate_team_score(["anonymous team", "previous failed project"])
        expected = BASE_TEAM_SCORE + FLAG_ADJUSTMENTS["anonymous team"] + FLAG_ADJUSTMENTS["previous failed project"]
        assert score == max(0.0, expected)  # Clamped to 0
        assert score == 0.0

    def test_mixed_flags(self):
        """Test score with mixed positive and negative flags."""
        score = calculate_team_score(["tier-1 vc backed", "previous failed project"])
        expected = BASE_TEAM_SCORE + FLAG_ADJUSTMENTS["tier-1 vc backed"] + FLAG_ADJUSTMENTS["previous failed project"]
        assert score == expected
        assert score == 0.45

    def test_clamping_upper_bound(self):
        """Test score clamping to 1.0."""
        score = calculate_team_score(["doxxed team", "tier-1 vc backed", "successful prior exit"])
        assert score <= 1.0
        assert score == 1.0

    def test_clamping_lower_bound(self):
        """Test score clamping to 0.0."""
        score = calculate_team_score(["anonymous team", "previous failed project", "wash-trading VC"])
        assert score >= 0.0
        assert score == 0.0

    def test_unknown_flag_ignored(self):
        """Test that unknown flags are ignored."""
        score = calculate_team_score(["unknown flag", "fake flag"])
        assert score == BASE_TEAM_SCORE
        assert score == 0.5


class TestScoreToRiskLevel:
    """Test score_to_risk_level function."""

    def test_high_risk_threshold(self):
        """Test high risk threshold (< 0.4)."""
        assert score_to_risk_level(0.0) == "high"
        assert score_to_risk_level(0.2) == "high"
        assert score_to_risk_level(0.39) == "high"

    def test_medium_risk_threshold(self):
        """Test medium risk threshold (0.4-0.7)."""
        assert score_to_risk_level(0.4) == "medium"
        assert score_to_risk_level(0.5) == "medium"
        assert score_to_risk_level(0.7) == "medium"

    def test_low_risk_threshold(self):
        """Test low risk threshold (> 0.7)."""
        assert score_to_risk_level(0.71) == "low"
        assert score_to_risk_level(0.85) == "low"
        assert score_to_risk_level(1.0) == "low"

    def test_boundary_values(self):
        """Test exact boundary values."""
        assert score_to_risk_level(0.4) == "medium"  # Lower boundary
        assert score_to_risk_level(0.7) == "medium"  # Upper boundary
        assert score_to_risk_level(0.39999) == "high"
        assert score_to_risk_level(0.70001) == "low"


class TestInferTeamFlags:
    """Test infer_team_flags function."""

    def test_vc_backed_project(self):
        """Test VC-backed project gets positive flag."""
        project = RawProject(
            id="test-1",
            name="VCProject",
            sector="L2",
            stage="testnet",
            recent_funding=True,
            url="https://project.xyz",
            source="seed",
        )
        flags = infer_team_flags(project)
        assert "recent funding" in flags  # §196: 裸 recent_funding 不构成 tier-1

    def test_mainnet_project(self):
        """Test mainnet project gets doxxed flag."""
        project = RawProject(
            id="test-2",
            name="MainnetProject",
            sector="L2",
            stage="mainnet",
            recent_funding=False,
            url="https://project.xyz",
            source="seed",
        )
        flags = infer_team_flags(project)
        assert "doxxed team" in flags

    def test_anonymous_project(self):
        """Test project with no signals gets anonymous flag."""
        project = RawProject(
            id="test-3",
            name="AnonProject",
            sector="DeFi",
            stage="ideation",
            recent_funding=False,
            url=None,
            source="seed",
        )
        flags = infer_team_flags(project)
        assert "anonymous team" in flags

    def test_testnet_project_neutral(self):
        """Test testnet project with URL gets no flags."""
        project = RawProject(
            id="test-4",
            name="TestnetProject",
            sector="Gaming",
            stage="testnet",
            recent_funding=False,
            url="https://project.xyz",
            source="seed",
        )
        flags = infer_team_flags(project)
        assert len(flags) == 0

    def test_combined_signals(self):
        """Test project with multiple positive signals."""
        project = RawProject(
            id="test-5",
            name="StrongProject",
            sector="L2",
            stage="mainnet",
            recent_funding=True,
            url="https://project.xyz",
            source="seed",
        )
        flags = infer_team_flags(project)
        assert "recent funding" in flags  # §196: 裸 recent_funding 不构成 tier-1
        assert "doxxed team" in flags


class TestInferTeamType:
    """Test infer_team_type function."""

    def test_doxxed_type(self):
        """Test doxxed team type."""
        flags = ["doxxed team"]
        assert infer_team_type(flags) == "doxxed"

        flags = ["doxxed team", "tier-1 vc backed"]
        assert infer_team_type(flags) == "doxxed"

    def test_anon_type(self):
        """Test anonymous team type."""
        flags = ["anonymous team"]
        assert infer_team_type(flags) == "anon"

        flags = ["anonymous team", "previous failed project"]
        assert infer_team_type(flags) == "anon"

    def test_semi_anon_type(self):
        """Test semi-anonymous team type (VC but not doxxed)."""
        flags = ["tier-1 vc backed"]
        assert infer_team_type(flags) == "semi_anon"

    def test_unknown_type(self):
        """Test unknown team type (no flags)."""
        flags = []
        assert infer_team_type(flags) == "unknown"

    def test_priority_doxxed_over_anon(self):
        """Test that doxxed flag takes priority if both present."""
        flags = ["doxxed team", "anonymous team"]  # Contradictory
        assert infer_team_type(flags) == "doxxed"


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self):
        """Test project with minimal fields."""
        project = RawProject(
            id="test-minimal",
            name="MinimalProject",
            sector=None,
            stage=None,
            url=None,
            recent_funding=False,
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        # Should handle gracefully with defaults
        assert result_state.team is not None
        assert result_state.team.team_score >= 0.0
        assert result_state.team.team_score <= 1.0
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_all_stages(self):
        """Test all project stages."""
        stages = ["ideation", "testnet", "mainnet"]

        for stage in stages:
            project = RawProject(
                id=f"test-{stage}",
                name=f"Project-{stage}",
                sector="L2",
                stage=stage,
                recent_funding=False,
                url="https://project.xyz",
                source="seed",
            )

            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            agent = TeamAgent()
            result_state = await agent.run(state)

            assert result_state.team is not None
            assert len(result_state.errors) == 0


class TestDataConsistency:
    """Test data model consistency."""

    @pytest.mark.asyncio
    async def test_team_result_schema(self):
        """Test that TeamResult matches schema."""
        project = RawProject(
            id="test-schema",
            name="SchemaTest",
            sector="L2",
            stage="testnet",
            recent_funding=True,
            url="https://test.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None

        # Check required fields
        assert hasattr(result_state.team, "team_score")
        assert hasattr(result_state.team, "team_flags")
        assert hasattr(result_state.team, "team_type")

        # Check types
        assert isinstance(result_state.team.team_score, float)
        assert isinstance(result_state.team.team_flags, list)
        assert isinstance(result_state.team.team_type, str)

        # Check constraints
        assert 0.0 <= result_state.team.team_score <= 1.0
        assert result_state.team.team_type in ["doxxed", "semi_anon", "anon", "unknown"]

    @pytest.mark.asyncio
    async def test_team_result_serialization(self):
        """Test that TeamResult can be serialized."""
        project = RawProject(id="test-serialize", name="SerializeTest", sector="L2", stage="testnet", source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TeamAgent()
        result_state = await agent.run(state)

        assert result_state.team is not None

        # Should be able to convert to dict
        team_dict = result_state.team.model_dump()
        assert isinstance(team_dict, dict)
        assert "team_score" in team_dict
        assert "team_flags" in team_dict
        assert "team_type" in team_dict
