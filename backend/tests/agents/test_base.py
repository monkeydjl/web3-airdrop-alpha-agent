"""Tests for Base Agent and core data structures.

Reference:
- backend/app/agents/base.py
"""

from datetime import UTC, datetime

import pytest

from app.agents.base import (
    AgentContext,
    AgentError,
    BaseAgent,
    NarrativeResult,
    PipelineState,
    RawProject,
    RiskResult,
    TeamResult,
    TokenomicsResult,
)


class TestRawProject:
    """Test RawProject data structure."""

    def test_minimal_creation(self):
        """Test creating RawProject with minimal fields."""
        project = RawProject(
            id="test-001",
            name="TestProject",
            source="seed",
        )

        assert project.id == "test-001"
        assert project.name == "TestProject"
        assert project.source == "seed"
        assert project.url is None
        assert project.sector is None
        assert project.stage is None

    def test_full_creation(self):
        """Test creating RawProject with all fields."""
        project = RawProject(
            id="test-001",
            name="LayerX",
            url="https://layerx.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
        )

        assert project.id == "test-001"
        assert project.name == "LayerX"
        assert project.url == "https://layerx.xyz"
        assert project.sector == "L2"
        assert project.stage == "testnet"
        assert project.has_testnet is True
        assert project.has_points_program is True
        assert project.no_token_yet is True
        assert project.recent_funding is True

    def test_created_at_auto_set(self):
        """Test that created_at is automatically set."""
        project = RawProject(
            id="test-001",
            name="TestProject",
            source="seed",
        )

        assert project.created_at is not None
        assert isinstance(project.created_at, datetime)

    def test_boolean_defaults(self):
        """Test that boolean fields default to False."""
        project = RawProject(
            id="test-001",
            name="TestProject",
            source="seed",
        )

        assert project.has_testnet is False
        assert project.has_points_program is False
        assert project.no_token_yet is False
        assert project.recent_funding is False


class TestAgentContext:
    """Test AgentContext data structure."""

    def test_default_creation(self):
        """Test creating AgentContext with defaults."""
        context = AgentContext(run_id="test-run")

        assert context.run_id == "test-run"
        assert context.enable_llm is False
        assert context.llm_model == "gpt-4o-mini"

    def test_custom_config(self):
        """Test creating AgentContext with custom config."""
        context = AgentContext(
            run_id="test-run",
            enable_llm=True,
            llm_model="gpt-4",
            max_concurrent_projects=20,
        )

        assert context.enable_llm is True
        assert context.llm_model == "gpt-4"
        assert context.max_concurrent_projects == 20


class TestAgentError:
    """Test AgentError data structure."""

    def test_error_creation(self):
        """Test creating AgentError."""
        error = AgentError(
            agent_name="narrative",
            kind="llm_error",
            message="API timeout",
            project_id="test-001",
        )

        assert error.agent_name == "narrative"
        assert error.kind == "llm_error"
        assert error.message == "API timeout"
        assert error.project_id == "test-001"

    def test_error_to_dict(self):
        """Test converting AgentError to dict."""
        error = AgentError(
            agent_name="team",
            kind="data_missing",
            message="No URL provided",
            project_id="test-002",
        )

        error_dict = error.to_dict()

        assert error_dict["agent_name"] == "team"
        assert error_dict["kind"] == "data_missing"
        assert error_dict["message"] == "No URL provided"
        assert error_dict["project_id"] == "test-002"


class TestPipelineState:
    """Test PipelineState data structure."""

    @pytest.fixture
    def project(self):
        return RawProject(
            id="test-001",
            name="TestProject",
            sector="L2",
            stage="testnet",
            source="seed",
        )

    @pytest.fixture
    def context(self):
        return AgentContext(run_id="test-run")

    def test_state_creation(self, project, context):
        """Test creating PipelineState."""
        state = PipelineState(project=project, context=context)

        assert state.project.id == "test-001"
        assert state.context.run_id == "test-run"
        assert state.narrative is None
        assert state.team is None
        assert state.risk is None
        assert state.tokenomics is None
        assert state.score is None
        assert state.label is None

    def test_add_error(self, project, context):
        """Test adding errors to state."""
        state = PipelineState(project=project, context=context)

        error = AgentError(
            agent_name="narrative",
            kind="test_error",
            message="Test",
            project_id=project.id,
        )

        state.add_error(error)

        assert len(state.errors) == 1
        assert state.errors[0].agent_name == "narrative"

    def test_timestamps(self, project, context):
        """Test state timestamps."""
        state = PipelineState(project=project, context=context)

        assert state.started_at is not None
        assert state.completed_at is None

        state.completed_at = datetime.now(UTC)
        assert state.completed_at is not None

    def test_set_narrative_result(self, project, context):
        """Test setting narrative result."""
        state = PipelineState(project=project, context=context)

        narrative = NarrativeResult(
            sector="L2",
            stage="growth",
            heat_score=0.85,
            timing="early",
        )

        state.narrative = narrative

        assert state.narrative.sector == "L2"
        assert state.narrative.heat_score == 0.85

    def test_set_team_result(self, project, context):
        """Test setting team result."""
        state = PipelineState(project=project, context=context)

        team = TeamResult(
            team_score=0.75,
            team_flags=["tier-1 vc backed"],
            team_type="semi_anon",
        )

        state.team = team

        assert state.team.team_score == 0.75
        assert "tier-1 vc backed" in state.team.team_flags

    def test_set_risk_result(self, project, context):
        """Test setting risk result."""
        state = PipelineState(project=project, context=context)

        risk = RiskResult(
            token_risk=0.45,
            risk_flags=["risk estimate uncertain"],
            unlock_pressure="medium",
        )

        state.risk = risk

        assert state.risk.token_risk == 0.45
        assert state.risk.unlock_pressure == "medium"

    def test_set_tokenomics_result(self, project, context):
        """Test setting tokenomics result."""
        state = PipelineState(project=project, context=context)

        tokenomics = TokenomicsResult(
            vc_share=0.25,
            team_share=0.20,
            unlock_penalty=0.35,
        )

        state.tokenomics = tokenomics

        assert state.tokenomics.vc_share == 0.25
        assert state.tokenomics.team_share == 0.20


class TestBaseAgent:
    """Test BaseAgent base class."""

    class DummyAgent(BaseAgent):
        """Dummy agent implementation for testing."""

        def __init__(self):
            super().__init__("test_agent")

        async def run(self, state: PipelineState) -> PipelineState:
            self._log_start(state)
            # Simple test logic
            state.score = 100
            self._log_complete(state, 10.0)
            return state

    @pytest.mark.asyncio
    async def test_base_agent_name(self):
        """Test base agent has name."""
        agent = self.DummyAgent()
        assert agent.name == "test_agent"

    @pytest.mark.asyncio
    async def test_base_agent_run(self):
        """Test base agent run method."""
        agent = self.DummyAgent()

        project = RawProject(
            id="test-001",
            name="TestProject",
            source="seed",
        )
        context = AgentContext(run_id="test-run")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)

        assert result.score == 100


class TestResultStructures:
    """Test result data structures."""

    def test_narrative_result(self):
        """Test NarrativeResult creation."""
        result = NarrativeResult(
            sector="L2",
            stage="growth",
            heat_score=0.85,
            timing="early",
        )

        assert result.sector == "L2"
        assert result.stage == "growth"
        assert result.heat_score == 0.85
        assert result.timing == "early"

    def test_team_result(self):
        """Test TeamResult creation."""
        result = TeamResult(
            team_score=0.75,
            team_flags=["doxxed team", "tier-1 vc backed"],
            team_type="doxxed",
        )

        assert result.team_score == 0.75
        assert len(result.team_flags) == 2
        assert result.team_type == "doxxed"

    def test_risk_result(self):
        """Test RiskResult creation."""
        result = RiskResult(
            token_risk=0.45,
            risk_flags=["risk estimate uncertain"],
            unlock_pressure="medium",
        )

        assert result.token_risk == 0.45
        assert len(result.risk_flags) == 1
        assert result.unlock_pressure == "medium"

    def test_tokenomics_result(self):
        """Test TokenomicsResult creation."""
        result = TokenomicsResult(
            vc_share=0.30,
            team_share=0.25,
            unlock_penalty=0.40,
        )

        assert result.vc_share == 0.30
        assert result.team_share == 0.25
        assert result.unlock_penalty == 0.40


class TestStateValidation:
    """Test state validation and edge cases."""

    @pytest.fixture
    def project(self):
        return RawProject(
            id="test-001",
            name="TestProject",
            source="seed",
        )

    @pytest.fixture
    def context(self):
        return AgentContext(run_id="test-run")

    def test_multiple_errors(self, project, context):
        """Test adding multiple errors."""
        state = PipelineState(project=project, context=context)

        error1 = AgentError(
            agent_name="narrative",
            kind="error1",
            message="Error 1",
            project_id=project.id,
        )

        error2 = AgentError(
            agent_name="team",
            kind="error2",
            message="Error 2",
            project_id=project.id,
        )

        state.add_error(error1)
        state.add_error(error2)

        assert len(state.errors) == 2
        assert state.errors[0].agent_name == "narrative"
        assert state.errors[1].agent_name == "team"

    def test_state_immutability_of_project(self, project, context):
        """Test that project reference remains stable."""
        state = PipelineState(project=project, context=context)

        original_id = state.project.id
        state.score = 75

        assert state.project.id == original_id

    def test_confidence_and_reason(self, project, context):
        """Test confidence and reason fields."""
        state = PipelineState(project=project, context=context)

        state.confidence = 0.75
        state.reason = ["reason 1", "reason 2", "reason 3"]

        assert state.confidence == 0.75
        assert len(state.reason) == 3

    def test_all_results_populated(self, project, context):
        """Test state with all results populated."""
        state = PipelineState(project=project, context=context)

        state.narrative = NarrativeResult(
            sector="L2",
            stage="growth",
            heat_score=0.85,
            timing="early",
        )

        state.team = TeamResult(
            team_score=0.75,
            team_flags=[],
            team_type="doxxed",
        )

        state.risk = RiskResult(
            token_risk=0.45,
            risk_flags=[],
            unlock_pressure="medium",
        )

        state.tokenomics = TokenomicsResult(
            vc_share=0.30,
            team_share=0.25,
            unlock_penalty=0.35,
        )

        state.score = 75
        state.label = "FARM"
        state.confidence = 1.0
        state.reason = ["test reason"]

        # All fields should be populated
        assert state.narrative is not None
        assert state.team is not None
        assert state.risk is not None
        assert state.tokenomics is not None
        assert state.score == 75
        assert state.label == "FARM"
        assert state.confidence == 1.0
        assert len(state.reason) == 1
