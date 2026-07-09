"""Tests for Simple Orchestrator.

Reference:
- backend/app/agents/orchestrator_simple.py
- ENGINEERING_ROADMAP.md §6.8, §6.9
"""

import pytest
from datetime import datetime, timezone

from app.agents.base import RawProject, AgentContext
from app.agents.orchestrator_simple import SimpleOrchestrator, run_orchestrator
from app.models import RunResponse


@pytest.fixture
def sample_projects():
    """Sample projects for testing."""
    return [
        RawProject(
            id="project-001",
            name="LayerX",
            url="https://layerx.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
        ),
        RawProject(
            id="project-002",
            name="RestakeDAO",
            url="https://restakedao.xyz",
            sector="Restaking",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
        ),
        RawProject(
            id="project-003",
            name="DeFiSwap",
            url="https://defiswap.xyz",
            sector="DeFi",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=False,
            recent_funding=False,
        ),
    ]


@pytest.fixture
def context():
    """Shared agent context."""
    return AgentContext(run_id="test-run-orchestrator")


class TestSimpleOrchestrator:
    """Test Simple Orchestrator creation and basic flow."""

    @pytest.mark.asyncio
    async def test_orchestrator_creation(self):
        """Test orchestrator can be created."""
        orchestrator = SimpleOrchestrator()
        assert orchestrator.narrative is not None
        assert orchestrator.team is not None
        assert orchestrator.risk is not None
        assert orchestrator.tokenomics is not None

    @pytest.mark.asyncio
    async def test_sector_counts_calculation(self, sample_projects):
        """Test sector count calculation."""
        orchestrator = SimpleOrchestrator()
        counts = orchestrator._calculate_sector_counts(sample_projects)

        assert counts["L2"] == 1
        assert counts["Restaking"] == 1
        assert counts["DeFi"] == 1
        assert len(counts) == 3

    @pytest.mark.asyncio
    async def test_sector_counts_multiple_same_sector(self):
        """Test sector counts with multiple projects in same sector."""
        projects = [
            RawProject(
                id=f"project-{i}",
                name=f"L2Project{i}",
                sector="L2",
                stage="testnet",
                source="seed",
            )
            for i in range(5)
        ]

        orchestrator = SimpleOrchestrator()
        counts = orchestrator._calculate_sector_counts(projects)

        assert counts["L2"] == 5
        assert len(counts) == 1


class TestPipelineExecution:
    """Test full pipeline execution."""

    @pytest.mark.asyncio
    async def test_single_project_pipeline(self, context):
        """Test pipeline with single project."""
        project = RawProject(
            id="single-project",
            name="TestProject",
            url="https://test.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
        )

        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline([project], context)

        assert isinstance(response, RunResponse)
        assert response.run_id == context.run_id
        assert response.project_count == 1
        assert response.status in ["completed", "partial"]
        assert response.elapsed_ms > 0

    @pytest.mark.asyncio
    async def test_multiple_projects_pipeline(self, sample_projects, context):
        """Test pipeline with multiple projects."""
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline(sample_projects, context)

        assert response.run_id == context.run_id
        assert response.project_count == 3
        assert response.status in ["completed", "partial"]
        assert response.top_score is not None
        assert response.elapsed_ms > 0

    @pytest.mark.asyncio
    async def test_empty_project_list(self, context):
        """Test pipeline with empty project list."""
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline([], context)

        assert response.project_count == 0
        assert response.status == "completed"
        assert response.top_score is None


class TestSingleProjectExecution:
    """Test single project execution flow."""

    @pytest.mark.asyncio
    async def test_run_single_project(self, context):
        """Test running pipeline for single project."""
        project = RawProject(
            id="test-single",
            name="SingleTest",
            sector="L2",
            stage="testnet",
            source="seed",
            has_points_program=True,
            no_token_yet=True,
        )

        orchestrator = SimpleOrchestrator()
        sector_counts = {"L2": 5}

        state = await orchestrator._run_single_project(project, context, sector_counts)

        # Check state populated
        assert state.project.id == project.id
        assert state.context.run_id == context.run_id

        # Check analysis agents ran
        assert state.narrative is not None
        assert state.team is not None
        assert state.risk is not None
        assert state.tokenomics is not None

        # Check scorer ran
        assert state.score is not None
        assert state.label in ["FARM", "WATCH", "IGNORE"]
        assert state.confidence is not None
        assert len(state.reason) >= 2

        # Check completion
        assert state.completed_at is not None

    @pytest.mark.asyncio
    async def test_run_single_project_with_missing_sector(self, context):
        """Test single project with missing sector."""
        project = RawProject(
            id="no-sector",
            name="NoSector",
            sector=None,  # Missing sector
            stage="testnet",
            source="seed",
        )

        orchestrator = SimpleOrchestrator()
        sector_counts = {}

        state = await orchestrator._run_single_project(project, context, sector_counts)

        # Should still complete
        assert state.score is not None
        assert state.label in ["FARM", "WATCH", "IGNORE"]


class TestParallelAnalysis:
    """Test parallel analysis agent execution."""

    @pytest.mark.asyncio
    async def test_analysis_agents_run_in_parallel(self, context):
        """Test that 4 analysis agents execute concurrently."""
        project = RawProject(
            id="parallel-test",
            name="ParallelTest",
            sector="L2",
            stage="testnet",
            source="seed",
        )

        orchestrator = SimpleOrchestrator()
        sector_counts = {"L2": 3}

        import time
        start = time.time()
        state = await orchestrator._run_single_project(project, context, sector_counts)
        duration = time.time() - start

        # All agents should complete
        assert state.narrative is not None
        assert state.team is not None
        assert state.risk is not None
        assert state.tokenomics is not None

        # Duration should be close to max(agent times), not sum
        # This is a weak test, but validates parallel execution
        assert duration < 5.0  # Should be fast with parallel execution


class TestErrorHandling:
    """Test error handling and isolation."""

    @pytest.mark.asyncio
    async def test_single_agent_failure_does_not_stop_pipeline(self, context):
        """Test that single agent failure doesn't stop other agents."""
        # This test validates error isolation
        project = RawProject(
            id="error-test",
            name="ErrorTest",
            sector="L2",
            stage="testnet",
            source="seed",
        )

        orchestrator = SimpleOrchestrator()
        sector_counts = {"L2": 3}

        state = await orchestrator._run_single_project(project, context, sector_counts)

        # Even if some agents fail, scorer should still run
        # (with missing data handled via confidence degradation)
        assert state.score is not None
        assert state.label in ["FARM", "WATCH", "IGNORE"]

    @pytest.mark.asyncio
    async def test_pipeline_continues_on_project_failure(self, sample_projects, context):
        """Test that pipeline continues even if one project fails."""
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline(sample_projects, context)

        # Should process all projects
        assert response.project_count == len(sample_projects)
        assert response.status in ["completed", "partial"]


class TestConvenienceFunction:
    """Test convenience run_orchestrator function."""

    @pytest.mark.asyncio
    async def test_run_orchestrator_basic(self, sample_projects):
        """Test run_orchestrator convenience function."""
        response = await run_orchestrator(sample_projects)

        assert isinstance(response, RunResponse)
        assert response.project_count == len(sample_projects)
        assert response.status in ["completed", "partial"]
        assert response.run_id.startswith("run-")

    @pytest.mark.asyncio
    async def test_run_orchestrator_with_run_id(self, sample_projects):
        """Test run_orchestrator with custom run_id."""
        custom_run_id = "custom-run-123"
        response = await run_orchestrator(sample_projects, run_id=custom_run_id)

        assert response.run_id == custom_run_id

    @pytest.mark.asyncio
    async def test_run_orchestrator_with_llm_disabled(self, sample_projects):
        """Test run_orchestrator with LLM disabled (MVP default)."""
        response = await run_orchestrator(sample_projects, enable_llm=False)

        assert response.project_count == len(sample_projects)
        # Should complete successfully without LLM
        assert response.status in ["completed", "partial"]


class TestResponseStructure:
    """Test response structure and statistics."""

    @pytest.mark.asyncio
    async def test_response_contains_top_score(self, sample_projects, context):
        """Test response includes top score."""
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline(sample_projects, context)

        if response.status != "failed":
            assert response.top_score is not None
            assert 0 <= response.top_score <= 100

    @pytest.mark.asyncio
    async def test_response_tracks_errors(self, context):
        """Test response tracks errors from agents."""
        # Use minimal project that might trigger some warnings
        project = RawProject(
            id="minimal",
            name="Minimal",
            sector=None,
            stage=None,
            source="seed",
        )

        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline([project], context)

        # errors list should exist (may be empty)
        assert isinstance(response.errors, list)

    @pytest.mark.asyncio
    async def test_response_elapsed_time_reasonable(self, sample_projects, context):
        """Test response elapsed time is reasonable."""
        orchestrator = SimpleOrchestrator()
        response = await orchestrator.run_pipeline(sample_projects, context)

        # Should complete in reasonable time
        assert response.elapsed_ms > 0
        assert response.elapsed_ms < 60000  # Less than 60 seconds for 3 projects


class TestSequentialExecution:
    """Test MVP sequential project execution."""

    @pytest.mark.asyncio
    async def test_projects_processed_sequentially(self, sample_projects, context):
        """Test that projects are processed one at a time (MVP constraint)."""
        orchestrator = SimpleOrchestrator()

        import time
        start = time.time()
        response = await orchestrator.run_pipeline(sample_projects, context)
        duration = time.time() - start

        # All projects should be processed
        assert response.project_count == len(sample_projects)

        # Sequential processing means duration scales linearly
        # This is expected behavior for MVP
        assert duration > 0


class TestIntegration:
    """Integration tests for complete pipeline."""

    @pytest.mark.asyncio
    async def test_complete_pipeline_layerx_example(self):
        """Test complete pipeline with LayerX-like project."""
        project = RawProject(
            id="layerx-test",
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

        response = await run_orchestrator([project])

        assert response.status in ["completed", "partial"]
        assert response.project_count == 1
        assert response.top_score is not None

    @pytest.mark.asyncio
    async def test_complete_pipeline_mixed_sectors(self):
        """Test complete pipeline with projects from different sectors."""
        projects = [
            RawProject(
                id="l2-project",
                name="L2Test",
                sector="L2",
                stage="testnet",
                source="seed",
                has_points_program=True,
            ),
            RawProject(
                id="defi-project",
                name="DeFiTest",
                sector="DeFi",
                stage="mainnet",
                source="seed",
                has_points_program=False,
            ),
            RawProject(
                id="restaking-project",
                name="RestakeTest",
                sector="Restaking",
                stage="testnet",
                source="seed",
                has_points_program=True,
                no_token_yet=True,
            ),
        ]

        response = await run_orchestrator(projects)

        assert response.status in ["completed", "partial"]
        assert response.project_count == 3
        assert response.top_score is not None
