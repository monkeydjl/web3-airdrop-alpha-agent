"""Unit tests for Tokenomics Agent.

Tests token economics analysis, VC/team allocation estimation, and unlock pressure.

Reference:
- app/agents/tokenomics.py
- DATA_SCORING_DICT.md §3.4 TokenomicsResult
- DATA_SCORING_DICT.md §5.7.1 Tokenomics unlock_penalty mapping
"""

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.tokenomics import (
    TokenomicsAgent,
    estimate_vc_share,
    estimate_team_share,
    infer_unlock_pressure,
    calculate_unlock_penalty,
    UNLOCK_PENALTY_MAP,
)


class TestTokenomicsAgent:
    """Test TokenomicsAgent class."""

    @pytest.mark.asyncio
    async def test_agent_creation(self):
        """Test agent creation and naming."""
        agent = TokenomicsAgent()
        assert agent.name == "tokenomics"

    @pytest.mark.asyncio
    async def test_good_tokenomics(self):
        """Test project with good tokenomics (mainnet + funding)."""
        project = RawProject(
            id="test-good",
            name="GoodTokenomics",
            sector="L2",
            stage="mainnet",
            recent_funding=True,
            url="https://good.xyz",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None
        assert result_state.tokenomics.vc_share == 0.25
        assert result_state.tokenomics.team_share == 0.20
        assert result_state.tokenomics.unlock_penalty > 0.0
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_medium_tokenomics(self):
        """Test project with medium tokenomics (testnet + funding)."""
        project = RawProject(
            id="test-medium",
            name="MediumTokenomics",
            sector="Restaking",
            stage="testnet",
            recent_funding=True,
            url="https://medium.xyz",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None
        assert result_state.tokenomics.vc_share == 0.30
        assert result_state.tokenomics.team_share == 0.25
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_high_risk_tokenomics(self):
        """Test project with high risk tokenomics (ideation + anon)."""
        project = RawProject(
            id="test-high-risk",
            name="HighRiskTokenomics",
            sector="DeFi",
            stage="ideation",
            recent_funding=True,
            url=None,
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None
        assert result_state.tokenomics.vc_share >= 0.30  # High VC
        assert result_state.tokenomics.team_share >= 0.30  # High team
        combined = result_state.tokenomics.vc_share + result_state.tokenomics.team_share
        assert combined > 0.55  # High pressure
        assert result_state.tokenomics.unlock_penalty == 0.65  # High penalty
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_low_allocation(self):
        """Test project with low allocation (no funding)."""
        project = RawProject(
            id="test-low",
            name="LowAllocation",
            sector="Gaming",
            stage="testnet",
            recent_funding=False,
            url="https://low.xyz",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None
        assert result_state.tokenomics.vc_share == 0.20  # Lower without funding
        assert result_state.tokenomics.team_share == 0.25
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_result_immutability(self):
        """Test that TokenomicsResult is immutable."""
        project = RawProject(
            id="test-immutable",
            name="Test",
            sector="L2",
            stage="testnet",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None

        # Try to modify - should raise FrozenInstanceError
        with pytest.raises(Exception):
            result_state.tokenomics.vc_share = 0.99


class TestEstimateVcShare:
    """Test estimate_vc_share function."""

    def test_mainnet_with_funding(self):
        """Test mainnet with funding gets moderate VC allocation."""
        project = RawProject(
            id="test-1",
            name="Test",
            sector="L2",
            stage="mainnet",
            recent_funding=True,
            source="seed"
        )
        vc_share = estimate_vc_share(project)
        assert vc_share == 0.25

    def test_testnet_with_funding(self):
        """Test testnet with funding gets higher VC allocation."""
        project = RawProject(
            id="test-2",
            name="Test",
            sector="L2",
            stage="testnet",
            recent_funding=True,
            source="seed"
        )
        vc_share = estimate_vc_share(project)
        assert vc_share == 0.30

    def test_ideation_with_funding(self):
        """Test ideation with funding gets highest VC allocation."""
        project = RawProject(
            id="test-3",
            name="Test",
            sector="L2",
            stage="ideation",
            recent_funding=True,
            source="seed"
        )
        vc_share = estimate_vc_share(project)
        assert vc_share == 0.35

    def test_no_funding(self):
        """Test project without funding gets lower VC allocation."""
        project = RawProject(
            id="test-4",
            name="Test",
            sector="L2",
            stage="testnet",
            recent_funding=False,
            source="seed"
        )
        vc_share = estimate_vc_share(project)
        assert vc_share == 0.20

    def test_all_in_range(self):
        """Test that all estimates are in valid range [0.0, 1.0]."""
        stages = ["mainnet", "testnet", "ideation"]
        fundings = [True, False]

        for stage in stages:
            for funding in fundings:
                project = RawProject(
                    id=f"test-{stage}-{funding}",
                    name="Test",
                    sector="L2",
                    stage=stage,
                    recent_funding=funding,
                    source="seed"
                )
                vc_share = estimate_vc_share(project)
                assert 0.0 <= vc_share <= 1.0


class TestEstimateTeamShare:
    """Test estimate_team_share function."""

    def test_mainnet(self):
        """Test mainnet gets standard team allocation."""
        project = RawProject(
            id="test-1",
            name="Test",
            sector="L2",
            stage="mainnet",
            url="https://test.xyz",
            source="seed"
        )
        team_share = estimate_team_share(project)
        assert team_share == 0.20

    def test_testnet(self):
        """Test testnet gets moderate team allocation."""
        project = RawProject(
            id="test-2",
            name="Test",
            sector="L2",
            stage="testnet",
            url="https://test.xyz",
            source="seed"
        )
        team_share = estimate_team_share(project)
        assert team_share == 0.25

    def test_ideation(self):
        """Test ideation gets higher team allocation."""
        project = RawProject(
            id="test-3",
            name="Test",
            sector="L2",
            stage="ideation",
            url="https://test.xyz",
            source="seed"
        )
        team_share = estimate_team_share(project)
        assert team_share == 0.30

    def test_anonymous_team(self):
        """Test anonymous team (no URL) gets highest allocation."""
        project = RawProject(
            id="test-4",
            name="Test",
            sector="L2",
            stage="testnet",
            url=None,
            source="seed"
        )
        team_share = estimate_team_share(project)
        assert team_share == 0.35

    def test_all_in_range(self):
        """Test that all estimates are in valid range [0.0, 1.0]."""
        stages = ["mainnet", "testnet", "ideation"]
        urls = ["https://test.xyz", None]

        for stage in stages:
            for url in urls:
                project = RawProject(
                    id=f"test-{stage}-{url is not None}",
                    name="Test",
                    sector="L2",
                    stage=stage,
                    url=url,
                    source="seed"
                )
                team_share = estimate_team_share(project)
                assert 0.0 <= team_share <= 1.0


class TestInferUnlockPressure:
    """Test infer_unlock_pressure function."""

    def test_low_pressure(self):
        """Test low unlock pressure (< 0.35)."""
        assert infer_unlock_pressure(0.10, 0.10) == "low"
        assert infer_unlock_pressure(0.15, 0.15) == "low"
        assert infer_unlock_pressure(0.20, 0.10) == "low"

    def test_medium_pressure(self):
        """Test medium unlock pressure (0.35-0.55)."""
        assert infer_unlock_pressure(0.20, 0.20) == "medium"
        assert infer_unlock_pressure(0.25, 0.25) == "medium"
        assert infer_unlock_pressure(0.30, 0.20) == "medium"

    def test_high_pressure(self):
        """Test high unlock pressure (> 0.55)."""
        assert infer_unlock_pressure(0.30, 0.30) == "high"
        assert infer_unlock_pressure(0.35, 0.35) == "high"
        assert infer_unlock_pressure(0.40, 0.40) == "high"

    def test_boundary_values(self):
        """Test exact boundary values."""
        assert infer_unlock_pressure(0.17, 0.17) == "low"  # 0.34
        assert infer_unlock_pressure(0.175, 0.175) == "medium"  # 0.35
        assert infer_unlock_pressure(0.275, 0.275) == "medium"  # 0.55
        assert infer_unlock_pressure(0.28, 0.28) == "high"  # 0.56

    def test_asymmetric_allocations(self):
        """Test asymmetric VC/team allocations."""
        assert infer_unlock_pressure(0.40, 0.10) == "medium"
        assert infer_unlock_pressure(0.10, 0.40) == "medium"
        assert infer_unlock_pressure(0.50, 0.10) == "high"


class TestCalculateUnlockPenalty:
    """Test calculate_unlock_penalty function."""

    def test_low_penalty(self):
        """Test low pressure maps to 0.15 penalty."""
        penalty = calculate_unlock_penalty("low")
        assert penalty == 0.15

    def test_medium_penalty(self):
        """Test medium pressure maps to 0.35 penalty."""
        penalty = calculate_unlock_penalty("medium")
        assert penalty == 0.35

    def test_high_penalty(self):
        """Test high pressure maps to 0.65 penalty."""
        penalty = calculate_unlock_penalty("high")
        assert penalty == 0.65

    def test_unknown_pressure(self):
        """Test unknown pressure uses default (0.35)."""
        penalty = calculate_unlock_penalty("unknown")
        assert penalty == 0.35

    def test_all_mappings(self):
        """Test all defined mappings."""
        for pressure, expected in UNLOCK_PENALTY_MAP.items():
            penalty = calculate_unlock_penalty(pressure)
            assert penalty == expected

    def test_penalties_in_range(self):
        """Test all penalties are in valid range [0.0, 1.0]."""
        for pressure in ["low", "medium", "high", "unknown"]:
            penalty = calculate_unlock_penalty(pressure)
            assert 0.0 <= penalty <= 1.0


class TestIntegration:
    """Test integration between functions."""

    @pytest.mark.asyncio
    async def test_full_pipeline(self):
        """Test full tokenomics analysis pipeline."""
        project = RawProject(
            id="test-pipeline",
            name="Pipeline",
            sector="L2",
            stage="testnet",
            recent_funding=True,
            url="https://pipeline.xyz",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        # Verify result
        assert result_state.tokenomics is not None
        t = result_state.tokenomics

        # Verify consistency
        combined = t.vc_share + t.team_share
        pressure = infer_unlock_pressure(t.vc_share, t.team_share)
        expected_penalty = calculate_unlock_penalty(pressure)
        assert t.unlock_penalty == expected_penalty

        # Verify ranges
        assert 0.0 <= t.vc_share <= 1.0
        assert 0.0 <= t.team_share <= 1.0
        assert 0.0 <= t.unlock_penalty <= 1.0
        assert 0.0 <= combined <= 2.0  # Theoretical max

    def test_pressure_penalty_consistency(self):
        """Test that unlock pressure and penalty are consistent."""
        test_cases = [
            (0.15, 0.15, "low", 0.15),
            (0.20, 0.20, "medium", 0.35),
            (0.30, 0.30, "high", 0.65),
        ]

        for vc, team, expected_pressure, expected_penalty in test_cases:
            pressure = infer_unlock_pressure(vc, team)
            penalty = calculate_unlock_penalty(pressure)

            assert pressure == expected_pressure
            assert penalty == expected_penalty


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
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        # Should handle gracefully with defaults
        assert result_state.tokenomics is not None
        assert 0.0 <= result_state.tokenomics.vc_share <= 1.0
        assert 0.0 <= result_state.tokenomics.team_share <= 1.0
        assert 0.0 <= result_state.tokenomics.unlock_penalty <= 1.0
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
                source="seed"
            )

            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            agent = TokenomicsAgent()
            result_state = await agent.run(state)

            assert result_state.tokenomics is not None
            assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_extreme_allocations(self):
        """Test that allocations don't exceed reasonable bounds."""
        # Anonymous ideation with funding (worst case)
        project = RawProject(
            id="test-extreme",
            name="ExtremeCase",
            sector="DeFi",
            stage="ideation",
            recent_funding=True,
            url=None,
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None
        t = result_state.tokenomics

        # Even in worst case, individual allocations shouldn't exceed 40%
        assert t.vc_share <= 0.40
        assert t.team_share <= 0.40

        # Combined shouldn't exceed 80% (leaving room for community)
        combined = t.vc_share + t.team_share
        assert combined <= 0.80


class TestDataConsistency:
    """Test data model consistency."""

    @pytest.mark.asyncio
    async def test_tokenomics_result_schema(self):
        """Test that TokenomicsResult matches schema."""
        project = RawProject(
            id="test-schema",
            name="SchemaTest",
            sector="L2",
            stage="testnet",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None

        # Check required fields
        assert hasattr(result_state.tokenomics, "vc_share")
        assert hasattr(result_state.tokenomics, "team_share")
        assert hasattr(result_state.tokenomics, "unlock_penalty")

        # Check types
        assert isinstance(result_state.tokenomics.vc_share, float)
        assert isinstance(result_state.tokenomics.team_share, float)
        assert isinstance(result_state.tokenomics.unlock_penalty, float)

        # Check constraints
        assert 0.0 <= result_state.tokenomics.vc_share <= 1.0
        assert 0.0 <= result_state.tokenomics.team_share <= 1.0
        assert 0.0 <= result_state.tokenomics.unlock_penalty <= 1.0

    @pytest.mark.asyncio
    async def test_tokenomics_result_serialization(self):
        """Test that TokenomicsResult can be serialized."""
        project = RawProject(
            id="test-serialize",
            name="SerializeTest",
            sector="L2",
            stage="testnet",
            source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = TokenomicsAgent()
        result_state = await agent.run(state)

        assert result_state.tokenomics is not None

        # Should be able to convert to dict
        tokenomics_dict = result_state.tokenomics.model_dump()
        assert isinstance(tokenomics_dict, dict)
        assert "vc_share" in tokenomics_dict
        assert "team_share" in tokenomics_dict
        assert "unlock_penalty" in tokenomics_dict
