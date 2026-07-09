"""Simple Orchestrator for MVP - Sequential execution of agent pipeline.

Orchestrates the complete scoring pipeline:
1. Collector (already run, we receive projects)
2. Parallel analysis: Narrative, Team, Risk, Tokenomics
3. Scorer

Reference:
- ENGINEERING_ROADMAP.md §6.8 Orchestrator
- ENGINEERING_ROADMAP.md §6.9 Multi-Project Concurrency (MVP: serial)
"""

import asyncio
import time
from typing import List, Dict
from datetime import datetime, timezone

import structlog

from app.agents.base import (
    BaseAgent,
    PipelineState,
    RawProject,
    AgentContext,
    AgentError,
)
from app.agents.narrative import NarrativeAgent
from app.agents.team import TeamAgent
from app.agents.risk import RiskAgent
from app.agents.tokenomics import TokenomicsAgent
from app.agents.scorer import ScorerAgent
from app.models import RunResponse

logger = structlog.get_logger(__name__)


class SimpleOrchestrator:
    """Simple MVP Orchestrator - Sequential project execution.

    Executes the complete pipeline for each project:
    - Runs 4 analysis agents in parallel per project
    - Runs Scorer to produce final score
    - Returns aggregated results

    MVP constraint: Projects processed serially (no cross-project concurrency).
    V2: Will add asyncio.Semaphore for bounded parallelism.
    """

    def __init__(self):
        """Initialize orchestrator with agents."""
        self.narrative = NarrativeAgent()
        self.team = TeamAgent()
        self.risk = RiskAgent()
        self.tokenomics = TokenomicsAgent()
        # Scorer initialized per-run with sector_counts

    async def run_pipeline(
        self,
        projects: List[RawProject],
        context: AgentContext,
    ) -> RunResponse:
        """Run complete pipeline for all projects.

        Args:
            projects: List of raw projects from collector
            context: Shared agent context

        Returns:
            RunResponse with aggregated results
        """
        start_time = time.time()

        logger.info(
            "orchestrator.pipeline_start",
            run_id=context.run_id,
            project_count=len(projects),
        )

        # Calculate sector counts for competition scoring
        sector_counts = self._calculate_sector_counts(projects)

        # Process each project sequentially (MVP)
        states: List[PipelineState] = []
        errors: List[Dict[str, str]] = []

        for idx, project in enumerate(projects):
            logger.info(
                "orchestrator.project_start",
                run_id=context.run_id,
                project_id=project.id,
                project_name=project.name,
                progress=f"{idx + 1}/{len(projects)}",
            )

            state = await self._run_single_project(project, context, sector_counts)
            states.append(state)

            # Collect errors
            for error in state.errors:
                errors.append(error.to_dict())

        # Calculate statistics
        elapsed_ms = (time.time() - start_time) * 1000
        scored_projects = [s for s in states if s.score is not None]

        if scored_projects:
            top_score = max(s.score for s in scored_projects)
            status = "completed" if not errors else "partial"
        else:
            top_score = None
            status = "failed" if errors else "completed"

        logger.info(
            "orchestrator.pipeline_complete",
            run_id=context.run_id,
            status=status,
            project_count=len(projects),
            scored_count=len(scored_projects),
            error_count=len(errors),
            elapsed_ms=elapsed_ms,
        )

        return RunResponse(
            run_id=context.run_id,
            status=status,
            project_count=len(projects),
            top_score=top_score,
            elapsed_ms=elapsed_ms,
            errors=errors,
        )

    async def _run_single_project(
        self,
        project: RawProject,
        context: AgentContext,
        sector_counts: Dict[str, int],
    ) -> PipelineState:
        """Run complete pipeline for a single project.

        Pipeline stages:
        1. Create pipeline state
        2. Run 4 analysis agents in parallel (Narrative, Team, Risk, Tokenomics)
        3. Run Scorer with results

        Args:
            project: Raw project data
            context: Agent context
            sector_counts: Pre-calculated sector counts for competition scoring

        Returns:
            Final pipeline state with score and label
        """
        state_start = time.time()

        # Initialize state
        state = PipelineState(
            project=project,
            context=context,
        )

        try:
            # Stage 1: Run analysis agents in parallel
            logger.info(
                "orchestrator.analysis_start",
                project_id=project.id,
                project_name=project.name,
            )

            # Execute 4 agents concurrently
            results = await asyncio.gather(
                self.narrative.run(state),
                self.team.run(state),
                self.risk.run(state),
                self.tokenomics.run(state),
                return_exceptions=True,
            )

            # Merge results back into state
            # Note: Each agent modifies state in-place, so we just need to check for exceptions
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
                    agent_names = ["narrative", "team", "risk", "tokenomics"]
                    error = AgentError(
                        agent_name=agent_names[idx],
                        kind="execution_error",
                        message=str(result),
                        project_id=project.id,
                    )
                    state.add_error(error)

            analysis_duration = (time.time() - state_start) * 1000
            logger.info(
                "orchestrator.analysis_complete",
                project_id=project.id,
                duration_ms=analysis_duration,
                narrative_present=state.narrative is not None,
                team_present=state.team is not None,
                risk_present=state.risk is not None,
                tokenomics_present=state.tokenomics is not None,
            )

            # Stage 2: Run Scorer
            scorer = ScorerAgent(sector_counts=sector_counts)
            state = await scorer.run(state)

            # Mark completion
            state.completed_at = datetime.now(timezone.utc)

            total_duration = (time.time() - state_start) * 1000
            logger.info(
                "orchestrator.project_complete",
                project_id=project.id,
                project_name=project.name,
                score=state.score,
                label=state.label,
                confidence=state.confidence,
                duration_ms=total_duration,
            )

        except Exception as e:
            # Catch any unexpected errors
            error = AgentError(
                agent_name="orchestrator",
                kind="unexpected_error",
                message=str(e),
                project_id=project.id,
            )
            state.add_error(error)

            logger.error(
                "orchestrator.project_failed",
                project_id=project.id,
                error=str(e),
            )

        return state

    def _calculate_sector_counts(self, projects: List[RawProject]) -> Dict[str, int]:
        """Calculate project count per sector for competition scoring.

        Args:
            projects: List of raw projects

        Returns:
            Dict mapping sector -> count
        """
        counts: Dict[str, int] = {}

        for project in projects:
            if project.sector:
                counts[project.sector] = counts.get(project.sector, 0) + 1

        logger.info(
            "orchestrator.sector_counts_calculated",
            total_sectors=len(counts),
            counts=counts,
        )

        return counts


async def run_orchestrator(
    projects: List[RawProject],
    run_id: str | None = None,
    enable_llm: bool = False,
) -> RunResponse:
    """Convenience function to run orchestrator.

    Args:
        projects: List of raw projects to process
        run_id: Optional run ID (generated if not provided)
        enable_llm: Whether to enable LLM enhancements (MVP: False)

    Returns:
        RunResponse with results
    """
    if run_id is None:
        run_id = f"run-{int(time.time())}"

    context = AgentContext(
        run_id=run_id,
        enable_llm=enable_llm,
    )

    orchestrator = SimpleOrchestrator()
    return await orchestrator.run_pipeline(projects, context)
