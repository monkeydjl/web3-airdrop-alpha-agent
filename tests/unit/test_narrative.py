"""Unit tests for Narrative Agent.

Tests:
- Sector profile lookup
- Heat score calculation
- Stage to timing mapping
- Unknown sector handling
- Result format validation
"""

import sys
sys.path.insert(0, 'backend')

import pytest

from app.agents.narrative import NarrativeAgent, stage_to_timing, SECTOR_PROFILE
from app.agents.base import AgentContext, RawProject, PipelineState


class TestStageToTiming:
    """Test stage to timing mapping"""

    def test_early_to_early(self):
        assert stage_to_timing("early") == "early"

    def test_growth_to_early(self):
        assert stage_to_timing("growth") == "early"

    def test_peak_to_peak(self):
        assert stage_to_timing("peak") == "peak"

    def test_mature_to_late(self):
        assert stage_to_timing("mature") == "late"

    def test_unknown_defaults_to_early(self):
        assert stage_to_timing("unknown") == "early"


class TestNarrativeAgent:
    """Test Narrative Agent functionality"""

    @pytest.mark.asyncio
    async def test_agent_creation(self):
        agent = NarrativeAgent()
        assert agent.name == "narrative"

    @pytest.mark.asyncio
    async def test_l2_sector(self):
        """Test L2 sector analysis"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-1",
            name="LayerX",
            sector="L2",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "L2"
        assert result.narrative.stage == "growth"
        assert result.narrative.timing == "early"
        assert 0.0 <= result.narrative.heat_score <= 1.0

    @pytest.mark.asyncio
    async def test_restaking_hot_narrative(self):
        """Test Restaking (hot narrative) sector"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-2",
            name="EigenLayer",
            sector="Restaking",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "Restaking"
        assert result.narrative.stage == "peak"
        assert result.narrative.timing == "peak"
        # High heat score for hot narrative
        assert result.narrative.heat_score >= 0.8

    @pytest.mark.asyncio
    async def test_mature_defi_sector(self):
        """Test mature DeFi sector"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-3",
            name="Uniswap",
            sector="DEX",
            stage="mainnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "DEX"
        assert result.narrative.stage == "mature"
        assert result.narrative.timing == "late"
        # Lower heat for mature sector
        assert result.narrative.heat_score < 0.8

    @pytest.mark.asyncio
    async def test_ai_early_sector(self):
        """Test AI (early) sector"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-4",
            name="WorldAI",
            sector="AI",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "AI"
        assert result.narrative.stage == "early"
        assert result.narrative.timing == "early"
        # High heat for emerging narrative
        assert result.narrative.heat_score >= 0.85

    @pytest.mark.asyncio
    async def test_unknown_sector(self):
        """Test unknown sector uses default profile"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-5",
            name="Unknown",
            sector="NewSector",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "NewSector"
        # Uses default profile
        assert result.narrative.stage == "growth"
        assert result.narrative.timing == "early"
        assert result.narrative.heat_score == 0.60

    @pytest.mark.asyncio
    async def test_none_sector(self):
        """Test None sector defaults to Unknown"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-6",
            name="NoSector",
            sector=None,
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.sector == "Unknown"

    @pytest.mark.asyncio
    async def test_heat_score_capped_at_one(self):
        """Test heat score is capped at 1.0"""
        agent = NarrativeAgent()

        # AI has high base_heat (0.88) and high momentum (1.3)
        # 0.88 * 1.3 = 1.144, should cap at 1.0
        project = RawProject(
            id="test-7",
            name="AIProject",
            sector="AI",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.narrative is not None
        assert result.narrative.heat_score <= 1.0

    @pytest.mark.asyncio
    async def test_result_immutable(self):
        """Test NarrativeResult is frozen (immutable)"""
        agent = NarrativeAgent()

        project = RawProject(
            id="test-8",
            name="Test",
            sector="L2",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="test-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        # NarrativeResult should be frozen
        with pytest.raises(Exception):  # Pydantic ValidationError or AttributeError
            result.narrative.heat_score = 0.99


class TestSectorProfiles:
    """Test sector profile configuration"""

    def test_all_profiles_have_required_keys(self):
        """All sector profiles should have required keys"""
        required_keys = {"base_heat", "stage", "momentum"}

        for sector, profile in SECTOR_PROFILE.items():
            assert required_keys.issubset(profile.keys()), \
                f"Sector {sector} missing required keys"

    def test_heat_scores_in_valid_range(self):
        """All base_heat values should be in [0, 1]"""
        for sector, profile in SECTOR_PROFILE.items():
            heat = profile["base_heat"]
            assert 0.0 <= heat <= 1.0, \
                f"Sector {sector} has invalid heat: {heat}"

    def test_stages_valid(self):
        """All stages should be valid values"""
        valid_stages = {"early", "growth", "peak", "mature"}

        for sector, profile in SECTOR_PROFILE.items():
            stage = profile["stage"]
            assert stage in valid_stages, \
                f"Sector {sector} has invalid stage: {stage}"

    def test_momentum_positive(self):
        """All momentum values should be positive"""
        for sector, profile in SECTOR_PROFILE.items():
            momentum = profile["momentum"]
            assert momentum > 0, \
                f"Sector {sector} has non-positive momentum: {momentum}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
