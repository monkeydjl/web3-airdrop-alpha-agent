"""Contract tests for BaseAgent.

Ensures all agent implementations follow the BaseAgent contract.
"""

import sys
sys.path.insert(0, 'backend')

import pytest
import uuid
from datetime import datetime

from app.agents.base import (
    BaseAgent,
    AgentContext,
    AgentError,
    PipelineState,
    RawProject,
)


class TestRawProject:
    """Test RawProject dataclass"""

    def test_raw_project_creation(self):
        project = RawProject(
            id=str(uuid.uuid4()),
            name="LayerX",
            url="https://layerx.xyz",
            sector="L2",
            stage="testnet",
            source="seed"
        )

        assert project.name == "LayerX"
        assert project.sector == "L2"
        assert project.stage == "testnet"
        assert project.source == "seed"

    def test_raw_project_to_dict(self):
        project = RawProject(
            id="test-id",
            name="Test",
            sector="DeFi",
            stage="mainnet",
            source="defillama"
        )

        data = project.to_dict()
        assert data["id"] == "test-id"
        assert data["name"] == "Test"
        assert data["sector"] == "DeFi"
        assert "created_at" in data


class TestAgentContext:
    """Test AgentContext dataclass"""

    def test_agent_context_defaults(self):
        context = AgentContext(run_id="run-001")

        assert context.run_id == "run-001"
        assert context.enable_llm is False
        assert context.llm_model == "gpt-4o-mini"

    def test_agent_context_to_dict(self):
        context = AgentContext(
            run_id="run-002",
            enable_llm=True,
            max_concurrent_projects=20
        )

        data = context.to_dict()
        assert data["run_id"] == "run-002"
        assert data["enable_llm"] is True
        assert data["max_concurrent_projects"] == 20


class TestAgentError:
    """Test AgentError dataclass"""

    def test_agent_error_creation(self):
        error = AgentError(
            agent_name="TestAgent",
            kind="validation_error",
            message="Invalid input",
            project_id="proj-001"
        )

        assert error.agent_name == "TestAgent"
        assert error.kind == "validation_error"
        assert error.message == "Invalid input"

    def test_agent_error_to_dict(self):
        error = AgentError(
            agent_name="TestAgent",
            kind="timeout",
            message="Request timeout"
        )

        data = error.to_dict()
        assert data["agent_name"] == "TestAgent"
        assert data["kind"] == "timeout"
        assert "timestamp" in data


class TestPipelineState:
    """Test PipelineState dataclass"""

    def test_pipeline_state_creation(self):
        project = RawProject(
            id="proj-001",
            name="Test",
            sector="L2",
            stage="testnet",
            source="seed"
        )
        context = AgentContext(run_id="run-001")

        state = PipelineState(project=project, context=context)

        assert state.project.name == "Test"
        assert state.context.run_id == "run-001"
        assert state.narrative is None
        assert state.team is None
        assert len(state.errors) == 0

    def test_add_error(self):
        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001")
        state = PipelineState(project=project, context=context)

        error = AgentError(
            agent_name="TestAgent",
            kind="error",
            message="Test error"
        )
        state.add_error(error)

        assert len(state.errors) == 1
        assert state.errors[0].agent_name == "TestAgent"

    def test_mark_completed(self):
        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001")
        state = PipelineState(project=project, context=context)

        assert state.completed_at is None

        state.mark_completed()

        assert state.completed_at is not None
        assert isinstance(state.completed_at, datetime)

    def test_to_dict(self):
        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001")
        state = PipelineState(project=project, context=context)

        data = state.to_dict()

        assert data["project"]["name"] == "Test"
        assert data["narrative"] is None
        assert data["team"] is None
        assert data["score"] is None
        assert isinstance(data["errors"], list)


class TestBaseAgent:
    """Test BaseAgent contract"""

    def test_base_agent_is_abstract(self):
        """BaseAgent cannot be instantiated directly"""

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            BaseAgent("test")

    def test_base_agent_requires_run_method(self):
        """Subclass must implement run() method"""

        class IncompleteAgent(BaseAgent):
            pass

        with pytest.raises(TypeError, match="Can't instantiate abstract class"):
            IncompleteAgent("incomplete")

    @pytest.mark.asyncio
    async def test_base_agent_concrete_implementation(self):
        """Concrete agent can be instantiated and run"""

        class ConcreteAgent(BaseAgent):
            async def run(self, state: PipelineState) -> PipelineState:
                self._log_start(state)
                # Simple implementation
                self._log_complete(state, 10.5)
                return state

        agent = ConcreteAgent("concrete")
        assert agent.name == "concrete"

        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001")
        state = PipelineState(project=project, context=context)

        result = await agent.run(state)
        assert result.project.name == "Test"

    @pytest.mark.asyncio
    async def test_llm_enhance_disabled_by_default(self):
        """LLM enhancement returns None when disabled"""

        class TestAgent(BaseAgent):
            async def run(self, state: PipelineState) -> PipelineState:
                return state

        agent = TestAgent("test")
        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001", enable_llm=False)
        state = PipelineState(project=project, context=context)

        result = await agent.llm_enhance(state, "test prompt")
        assert result is None

    @pytest.mark.asyncio
    async def test_llm_enhance_skipped_in_mvp(self):
        """LLM enhancement skipped in MVP even when enabled"""

        class TestAgent(BaseAgent):
            async def run(self, state: PipelineState) -> PipelineState:
                return state

        agent = TestAgent("test")
        project = RawProject(id="proj-001", name="Test", sector="L2", stage="testnet", source="seed")
        context = AgentContext(run_id="run-001", enable_llm=True)
        state = PipelineState(project=project, context=context)

        # MVP: returns None even with enable_llm=True
        result = await agent.llm_enhance(state, "test prompt")
        assert result is None


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
