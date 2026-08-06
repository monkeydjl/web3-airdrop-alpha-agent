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
from datetime import UTC, datetime
from typing import Any

import structlog

from app.agents.base import (
    AgentContext,
    AgentError,
    PipelineState,
    RawProject,
)
from app.agents.narrative import NarrativeAgent
from app.agents.risk import RiskAgent
from app.agents.scorer import ScorerAgent
from app.agents.team import TeamAgent
from app.agents.tokenomics import TokenomicsAgent
from app.config import settings
from app.models import RunResponse
from app.repository import ProjectRepository

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
        projects: list[RawProject],
        context: AgentContext,
        save_to_db: bool = True,
    ) -> RunResponse:
        """Run complete pipeline for all projects.

        Args:
            projects: List of raw projects from collector
            context: Shared agent context
            save_to_db: Whether to save results to database (default True)

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
        states: list[PipelineState] = []
        errors: list[dict[str, str]] = []

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
        top_score = max((s.score for s in scored_projects), default=None)

        # 先落库，再定状态。此前状态在持久化**之前**就算好了，于是"评分成功但一行都没
        # 写进去"依然返回 status=completed / error_count=0；上游 pipeline_run 又只看
        # state.score 就把 raw_projects 标成已处理，于是整批数据既没落库、也不再排队
        # 重试，而 DB 与 metrics 里都查不到任何痕迹。
        persisted_project_rows: list[dict[str, Any]] = []
        persist_failed = False
        if save_to_db and states:
            try:
                repo = ProjectRepository(
                    economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled
                )
                persisted_project_rows = repo.save_batch_with_rows(states)
            except Exception as e:
                persist_failed = True
                errors.append({"stage": "persist", "error": str(e)})
                logger.error(
                    "orchestrator.db_save_failed",
                    run_id=context.run_id,
                    error=str(e),
                    exc_info=True,
                )
            else:
                # save_batch_with_rows 会逐条吞掉单行异常，只有行数差额能暴露它们
                missing = len(states) - len(persisted_project_rows)
                if missing > 0:
                    persist_failed = True
                    errors.append(
                        {"stage": "persist", "error": f"{missing} of {len(states)} rows were not persisted"}
                    )
                logger.info(
                    "orchestrator.db_save_complete",
                    run_id=context.run_id,
                    saved_count=len(persisted_project_rows),
                    total_count=len(states),
                )

        if persist_failed:
            status = "partial" if persisted_project_rows else "failed"
        elif scored_projects:
            status = "completed" if not errors else "partial"
        else:
            status = "failed" if errors else "completed"

        logger.info(
            "orchestrator.pipeline_complete",
            run_id=context.run_id,
            status=status,
            project_count=len(projects),
            scored_count=len(scored_projects),
            persisted_count=len(persisted_project_rows),
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
            states=states,  # Include states for API access
            persisted_project_rows=persisted_project_rows,
        )

    async def _run_single_project(
        self,
        project: RawProject,
        context: AgentContext,
        sector_counts: dict[str, int],
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

            # Stage 1a: 独立 agent 并行执行（Risk 依赖 Tokenomics 结果，故拆到 1b）
            stage1_results = await asyncio.gather(
                self.narrative.run(state),
                self.team.run(state),
                self.tokenomics.run(state),
                return_exceptions=True,
            )
            # Stage 1b: Tokenomics 就绪后再跑 Risk，保证 token_risk 用真实解锁数据
            risk_result = await asyncio.gather(self.risk.run(state), return_exceptions=True)

            # Merge results back into state
            # Note: Each agent modifies state in-place, so we just need to check for exceptions
            results = [stage1_results[0], stage1_results[1], risk_result[0], stage1_results[2]]
            agent_names = ["narrative", "team", "risk", "tokenomics"]
            for idx, result in enumerate(results):
                if isinstance(result, Exception):
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
            state.completed_at = datetime.now(UTC)

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

    def _calculate_sector_counts(self, projects: list[RawProject]) -> dict[str, int]:
        """Calculate project count per sector for competition scoring.

        保持纯函数语义（只统计传入批次），这是 Golden 用例"同输入同输出"的前提。
        需要以全库为基准时请用 `global_sector_counts()`。

        Args:
            projects: List of raw projects

        Returns:
            Dict mapping sector -> count
        """
        counts: dict[str, int] = {}

        for project in projects:
            if project.sector:
                counts[project.sector] = counts.get(project.sector, 0) + 1

        logger.info(
            "orchestrator.sector_counts_calculated",
            total_sectors=len(counts),
            counts=counts,
        )

        return counts


def global_sector_counts(fallback: list[RawProject] | None = None) -> dict[str, int]:
    """以全库为基准的赛道计数，用于单项目重算路径。

    竞争度衡量"该赛道里有多少项目"，是项目全集的属性。批量评分时批次本身就是
    一个合理的样本，但单项目重算（如改完融资后触发 rescore）只会得到 {sector: 1}
    → 竞争度 100 分，而同一项目在 20 个项目的批次里只有 40 分——6.0 个加权分
    完全由"以什么方式触发重算"决定。此函数让重算路径与批量路径口径一致。
    """
    try:
        from app.repository import ProjectRepository

        counts = {str(sector): int(n) for sector, n in ProjectRepository().aggregate_counts("sector").items() if sector}
        if counts:
            return counts
    except Exception as exc:  # pragma: no cover - 冷启动/无库时回落
        logger.warning("orchestrator.global_sector_counts_unavailable", error=str(exc))

    counts = {}
    for project in fallback or []:
        if project.sector:
            counts[project.sector] = counts.get(project.sector, 0) + 1
    return counts


async def run_orchestrator(
    projects: list[RawProject],
    run_id: str | None = None,
    enable_llm: bool = False,
    save_to_db: bool = True,
) -> RunResponse:
    """Convenience function to run orchestrator.

    Args:
        projects: List of raw projects to process
        run_id: Optional run ID (generated if not provided)
        enable_llm: Whether to enable LLM enhancements (MVP: False)
        save_to_db: Whether to save results to database (default True)

    Returns:
        RunResponse with results
    """
    if run_id is None:
        run_id = f"run-{int(time.time())}"

    context = AgentContext(
        run_id=run_id,
        enable_llm=enable_llm,
        llm_discovery_score_threshold=settings.llm_discovery_score_threshold,
    )

    orchestrator = SimpleOrchestrator()
    return await orchestrator.run_pipeline(projects, context, save_to_db=save_to_db)
