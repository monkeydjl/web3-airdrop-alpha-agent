"""Unit tests for Risk Agent.

Tests risk assessment, token risk calculation, and sybil difficulty evaluation.

Reference:
- app/agents/risk.py
- DATA_SCORING_DICT.md §3.3 RiskResult
- DATA_SCORING_DICT.md §5.7.2 Risk token_risk heuristic
"""

import pytest
from pydantic import ValidationError

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.risk import (
    STAGE_RISK_FACTOR,
    RiskAgent,
    assess_farming_cost,
    assess_sybil_difficulty,
    calculate_airdrop_signal_subscore,
    calculate_token_risk,
    generate_risk_flags,
    infer_unlock_pressure,
)
from app.models import TokenomicsResult


class TestRiskAgent:
    """Test RiskAgent class."""

    @pytest.mark.asyncio
    async def test_agent_creation(self):
        """Test agent creation and naming."""
        agent = RiskAgent()
        assert agent.name == "risk"

    @pytest.mark.asyncio
    async def test_high_risk_project(self):
        """Test high-risk project (ideation, no signals)."""
        project = RawProject(
            id="test-high-risk",
            name="HighRisk",
            sector="DeFi",
            stage="ideation",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=False,
            url=None,
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None
        assert result_state.risk.token_risk > 0.5  # High risk
        assert result_state.risk.unlock_pressure in ["medium", "high"]
        assert "risk estimate uncertain" in result_state.risk.risk_flags
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_medium_risk_project(self):
        """Test medium-risk project (testnet with points)."""
        project = RawProject(
            id="test-med-risk",
            name="MediumRisk",
            sector="L2",
            stage="testnet",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            url="https://medium.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        # Add tokenomics
        state.tokenomics = TokenomicsResult(
            vc_share=0.25,
            team_share=0.20,
            unlock_penalty=0.35,
        )

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None
        assert 0.2 <= result_state.risk.token_risk <= 0.5
        assert result_state.risk.unlock_pressure in ["low", "medium"]
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_low_risk_project(self):
        """Test low-risk project (mainnet with good tokenomics)."""
        project = RawProject(
            id="test-low-risk",
            name="LowRisk",
            sector="Restaking",
            stage="mainnet",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=False,
            url="https://low.xyz",
            source="seed",
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        # Add good tokenomics
        state.tokenomics = TokenomicsResult(
            vc_share=0.15,
            team_share=0.15,
            unlock_penalty=0.20,
        )

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None
        assert result_state.risk.token_risk < 0.4  # Low risk
        assert result_state.risk.unlock_pressure in ["low", "medium"]
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_missing_tokenomics(self):
        """Test project with missing tokenomics data."""
        project = RawProject(
            id="test-missing", name="MissingTokenomics", sector="Gaming", stage="testnet", source="seed"
        )

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None
        assert "risk estimate uncertain" in result_state.risk.risk_flags
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_result_immutability(self):
        """Test that RiskResult is immutable."""
        project = RawProject(id="test-immutable", name="Test", sector="L2", stage="testnet", source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None

        # Try to modify - should raise FrozenInstanceError
        with pytest.raises(ValidationError):
            result_state.risk.token_risk = 0.99


class TestCalculateAirdropSignalSubscore:
    """Test calculate_airdrop_signal_subscore function."""

    def test_both_signals(self):
        """Test with both points and hint."""
        project = RawProject(
            id="test-1", name="Test", sector="L2", has_points_program=True, no_token_yet=True, source="seed"
        )
        score = calculate_airdrop_signal_subscore(project)
        assert score == 100.0

    def test_points_only(self):
        """Test with points program only."""
        project = RawProject(
            id="test-2", name="Test", sector="L2", has_points_program=True, no_token_yet=False, source="seed"
        )
        score = calculate_airdrop_signal_subscore(project)
        assert score == 60.0

    def test_hint_only(self):
        """Test with airdrop hint only (no testnet)."""
        project = RawProject(
            id="test-3",
            name="Test",
            sector="L2",
            stage="mainnet",
            has_points_program=False,
            no_token_yet=True,
            has_testnet=False,
            source="seed",
        )
        score = calculate_airdrop_signal_subscore(project)
        assert score == 60.0

    def test_no_token_and_testnet(self):
        """Test no_token_yet + testnet -> 85."""
        project = RawProject(
            id="test-3b",
            name="Test",
            sector="L2",
            stage="testnet",
            has_points_program=False,
            no_token_yet=True,
            has_testnet=True,
            source="seed",
        )
        score = calculate_airdrop_signal_subscore(project)
        assert score == 85.0

    def test_no_signals(self):
        """Test with no signals."""
        project = RawProject(
            id="test-4",
            name="Test",
            sector="L2",
            stage="mainnet",
            has_points_program=False,
            no_token_yet=False,
            has_testnet=False,
            source="seed",
        )
        score = calculate_airdrop_signal_subscore(project)
        assert score == 20.0


class TestCalculateTokenRisk:
    """Test calculate_token_risk function."""

    def test_with_tokenomics(self):
        """Test token risk calculation with tokenomics data."""
        project = RawProject(
            id="test-1",
            name="Test",
            sector="L2",
            stage="testnet",
            has_points_program=True,
            no_token_yet=True,
            source="seed",
        )

        # High tokenomics risk
        token_risk = calculate_token_risk(project, tokenomics_risk=0.75)
        assert token_risk > 0.4  # Should be elevated

        # Low tokenomics risk
        token_risk = calculate_token_risk(project, tokenomics_risk=0.20)
        assert token_risk < 0.4  # Should be lower

    def test_without_tokenomics(self):
        """Test token risk calculation without tokenomics (default 0.5)."""
        project = RawProject(
            id="test-2",
            name="Test",
            sector="L2",
            stage="testnet",
            has_points_program=True,
            no_token_yet=True,
            source="seed",
        )

        token_risk = calculate_token_risk(project, tokenomics_risk=None)
        assert 0.0 <= token_risk <= 1.0

    def test_stage_factors(self):
        """Test different stage factors."""
        for stage, expected_factor in STAGE_RISK_FACTOR.items():
            project = RawProject(
                id=f"test-{stage}",
                name="Test",
                sector="L2",
                stage=stage,
                has_points_program=True,
                no_token_yet=True,
                source="seed",
            )

            token_risk = calculate_token_risk(project, tokenomics_risk=0.5)
            assert token_risk == pytest.approx(0.3 + 0.2 * expected_factor)

    def test_clamping(self):
        """Test that token risk is clamped to [0.0, 1.0]."""
        project = RawProject(
            id="test-clamp",
            name="Test",
            sector="L2",
            stage="ideation",
            has_points_program=False,
            no_token_yet=False,
            source="seed",
        )

        # Extreme values should still clamp
        token_risk = calculate_token_risk(project, tokenomics_risk=1.0)
        assert 0.0 <= token_risk <= 1.0

        token_risk = calculate_token_risk(project, tokenomics_risk=0.0)
        assert 0.0 <= token_risk <= 1.0

    def test_formula_components(self):
        """Test formula: 0.6*tokenomics + 0.2*(1-airdrop/100) + 0.2*stage."""
        project = RawProject(
            id="test-formula",
            name="Test",
            sector="L2",
            stage="testnet",  # stage_factor = 0.35
            has_points_program=True,
            no_token_yet=True,  # airdrop = 100
            source="seed",
        )

        tokenomics_risk = 0.4
        token_risk = calculate_token_risk(project, tokenomics_risk)

        # Expected: 0.6*0.4 + 0.2*(1-1.0) + 0.2*0.35 = 0.24 + 0 + 0.07 = 0.31
        assert abs(token_risk - 0.31) < 0.01


class TestAssessSybilDifficulty:
    """Test assess_sybil_difficulty function."""

    def test_mainnet_high(self):
        """Test mainnet projects have high sybil difficulty."""
        project = RawProject(id="test-1", name="Test", sector="L2", stage="mainnet", source="seed")
        difficulty = assess_sybil_difficulty(project)
        assert difficulty == "high"

    def test_testnet_with_points_high(self):
        """Test testnet with points has high difficulty."""
        project = RawProject(
            id="test-2",
            name="Test",
            sector="L2",
            stage="testnet",
            has_testnet=True,
            has_points_program=True,
            source="seed",
        )
        difficulty = assess_sybil_difficulty(project)
        assert difficulty == "high"

    def test_testnet_medium(self):
        """Test testnet without points has medium difficulty."""
        project = RawProject(id="test-3", name="Test", sector="L2", stage="testnet", has_testnet=True, source="seed")
        difficulty = assess_sybil_difficulty(project)
        assert difficulty == "medium"

    def test_ideation_low(self):
        """Test ideation projects have low difficulty."""
        project = RawProject(id="test-4", name="Test", sector="L2", stage="ideation", source="seed")
        difficulty = assess_sybil_difficulty(project)
        assert difficulty == "low"


class TestAssessFarmingCost:
    """Test assess_farming_cost function."""

    def test_mainnet_high(self):
        """Test mainnet has high farming cost."""
        project = RawProject(id="test-1", name="Test", sector="L2", stage="mainnet", source="seed")
        cost = assess_farming_cost(project)
        assert cost == "high"

    def test_testnet_medium(self):
        """Test testnet has medium farming cost."""
        project = RawProject(id="test-2", name="Test", sector="L2", stage="testnet", source="seed")
        cost = assess_farming_cost(project)
        assert cost == "medium"

    def test_points_medium(self):
        """Test points program has medium cost."""
        project = RawProject(
            id="test-3", name="Test", sector="L2", stage="ideation", has_points_program=True, source="seed"
        )
        cost = assess_farming_cost(project)
        assert cost == "medium"

    def test_ideation_low(self):
        """Test ideation without points has low cost."""
        project = RawProject(
            id="test-4", name="Test", sector="L2", stage="ideation", has_points_program=False, source="seed"
        )
        cost = assess_farming_cost(project)
        assert cost == "low"


class TestInferUnlockPressure:
    """Test infer_unlock_pressure function."""

    def test_low_pressure(self):
        """Test low unlock pressure (< 0.35)."""
        assert infer_unlock_pressure(0.0) == "low"
        assert infer_unlock_pressure(0.2) == "low"
        assert infer_unlock_pressure(0.34) == "low"

    def test_medium_pressure(self):
        """Test medium unlock pressure (0.35-0.65)."""
        assert infer_unlock_pressure(0.35) == "medium"
        assert infer_unlock_pressure(0.5) == "medium"
        assert infer_unlock_pressure(0.65) == "medium"

    def test_high_pressure(self):
        """Test high unlock pressure (> 0.65)."""
        assert infer_unlock_pressure(0.66) == "high"
        assert infer_unlock_pressure(0.8) == "high"
        assert infer_unlock_pressure(1.0) == "high"

    def test_boundary_values(self):
        """Test exact boundary values."""
        assert infer_unlock_pressure(0.35) == "medium"  # Lower boundary
        assert infer_unlock_pressure(0.65) == "medium"  # Upper boundary
        assert infer_unlock_pressure(0.34999) == "low"
        assert infer_unlock_pressure(0.65001) == "high"


class TestGenerateRiskFlags:
    """Test generate_risk_flags function."""

    def test_high_token_risk_flag(self):
        """Test high token risk generates flag."""
        project = RawProject(
            id="test-1", name="Test", sector="L2", stage="testnet", has_points_program=True, source="seed"
        )
        flags = generate_risk_flags(project, token_risk=0.7, sybil_difficulty="high", tokenomics_missing=False)
        assert "high token structure risk" in flags

    def test_easy_sybil_flag(self):
        """Test low sybil difficulty generates flag."""
        project = RawProject(id="test-2", name="Test", sector="L2", stage="ideation", source="seed")
        flags = generate_risk_flags(project, token_risk=0.3, sybil_difficulty="low", tokenomics_missing=False)
        assert "easy to sybil farm" in flags

    def test_missing_tokenomics_flag(self):
        """Test missing tokenomics generates flag."""
        project = RawProject(id="test-3", name="Test", sector="L2", stage="testnet", source="seed")
        flags = generate_risk_flags(project, token_risk=0.5, sybil_difficulty="medium", tokenomics_missing=True)
        assert "risk estimate uncertain" in flags

    def test_ideation_flag(self):
        """Test ideation stage generates flag."""
        project = RawProject(id="test-4", name="Test", sector="L2", stage="ideation", source="seed")
        flags = generate_risk_flags(project, token_risk=0.5, sybil_difficulty="medium", tokenomics_missing=False)
        assert "no product yet" in flags

    def test_weak_signals_flag(self):
        """Test weak airdrop signals generate flag."""
        project = RawProject(
            id="test-5",
            name="Test",
            sector="L2",
            stage="testnet",
            has_points_program=False,
            no_token_yet=False,
            source="seed",
        )
        flags = generate_risk_flags(project, token_risk=0.5, sybil_difficulty="medium", tokenomics_missing=False)
        assert "weak airdrop signals" in flags

    def test_multiple_flags(self):
        """Test multiple risk flags."""
        project = RawProject(
            id="test-6",
            name="Test",
            sector="L2",
            stage="ideation",
            has_points_program=False,
            no_token_yet=False,
            source="seed",
        )
        flags = generate_risk_flags(project, token_risk=0.7, sybil_difficulty="low", tokenomics_missing=True)
        assert len(flags) >= 3
        assert "high token structure risk" in flags
        assert "easy to sybil farm" in flags
        assert "risk estimate uncertain" in flags

    def test_no_flags(self):
        """Test project with no risk flags."""
        project = RawProject(
            id="test-7",
            name="Test",
            sector="L2",
            stage="mainnet",
            has_points_program=True,
            no_token_yet=True,
            source="seed",
        )
        flags = generate_risk_flags(project, token_risk=0.2, sybil_difficulty="high", tokenomics_missing=False)
        assert len(flags) == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_missing_optional_fields(self):
        """Test project with minimal fields."""
        project = RawProject(id="test-minimal", name="MinimalProject", sector=None, stage=None, source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        # Should handle gracefully with defaults
        assert result_state.risk is not None
        assert 0.0 <= result_state.risk.token_risk <= 1.0
        assert result_state.risk.unlock_pressure in ["low", "medium", "high"]
        assert len(result_state.errors) == 0

    @pytest.mark.asyncio
    async def test_all_stages(self):
        """Test all project stages."""
        stages = ["ideation", "testnet", "mainnet"]

        for stage in stages:
            project = RawProject(id=f"test-{stage}", name=f"Project-{stage}", sector="L2", stage=stage, source="seed")

            context = AgentContext(run_id="test-001")
            state = PipelineState(project=project, context=context)

            agent = RiskAgent()
            result_state = await agent.run(state)

            assert result_state.risk is not None
            assert len(result_state.errors) == 0


class TestDataConsistency:
    """Test data model consistency."""

    @pytest.mark.asyncio
    async def test_risk_result_schema(self):
        """Test that RiskResult matches schema."""
        project = RawProject(id="test-schema", name="SchemaTest", sector="L2", stage="testnet", source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None

        # Check required fields
        assert hasattr(result_state.risk, "token_risk")
        assert hasattr(result_state.risk, "risk_flags")
        assert hasattr(result_state.risk, "unlock_pressure")

        # Check types
        assert isinstance(result_state.risk.token_risk, float)
        assert isinstance(result_state.risk.risk_flags, list)
        assert isinstance(result_state.risk.unlock_pressure, str)

        # Check constraints
        assert 0.0 <= result_state.risk.token_risk <= 1.0
        assert result_state.risk.unlock_pressure in ["low", "medium", "high"]

    @pytest.mark.asyncio
    async def test_risk_result_serialization(self):
        """Test that RiskResult can be serialized."""
        project = RawProject(id="test-serialize", name="SerializeTest", sector="L2", stage="testnet", source="seed")

        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        agent = RiskAgent()
        result_state = await agent.run(state)

        assert result_state.risk is not None

        # Should be able to convert to dict
        risk_dict = result_state.risk.model_dump()
        assert isinstance(risk_dict, dict)
        assert "token_risk" in risk_dict
        assert "risk_flags" in risk_dict
        assert "unlock_pressure" in risk_dict
