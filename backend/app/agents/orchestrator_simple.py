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
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Literal, cast

import structlog

from app import metrics
from app import tracing as _tracing
from app.agents.base import (
    AgentContext,
    AgentError,
    PipelineState,
    RawProject,
)
from app.agents.narrative import NarrativeAgent, canonical_sector_key
from app.agents.risk import RiskAgent
from app.agents.scorer import ScorerAgent
from app.agents.team import TeamAgent
from app.agents.tokenomics import TokenomicsAgent
from app.config import settings
from app.models import RunResponse
from app.repository import ProjectRepository
from app.tracing import end_span_with_error

logger = structlog.get_logger(__name__)


class SimpleOrchestrator:
    """Simple Orchestrator - Bounded parallel project execution (ADR-007 Level 1).

    Executes the complete pipeline for each project:
    - Runs 4 analysis agents in parallel per project
    - Runs Scorer to produce final score
    - Returns aggregated results

    Concurrency (ADR-007):
    - Level 1: Multiple projects run concurrently, bounded by an
      asyncio.Semaphore (settings.max_concurrent_projects). A single project
      failure is isolated and never blocks the rest of the batch.
    - Level 2: Per-project agent parallelism via asyncio.gather (in
      _run_single_project).
    """

    def __init__(self, max_concurrent: int | None = None):
        """Initialize orchestrator with agents and concurrency control.

        Args:
            max_concurrent: Maximum number of projects to process concurrently.
                Defaults to settings.max_concurrent_projects.
        """
        self.narrative = NarrativeAgent()
        self.team = TeamAgent()
        self.risk = RiskAgent()
        self.tokenomics = TokenomicsAgent()
        # Scorer initialized per-run with sector_counts
        self._semaphore = asyncio.Semaphore(
            max_concurrent if max_concurrent is not None else settings.max_concurrent_projects
        )

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
        # Merge batch counts with global DB counts (ADR-010 V2 cache)
        sector_counts = self._calculate_sector_counts(projects)
        if save_to_db:
            try:
                repo = ProjectRepository()
                # 用折叠后的全库分布，而不是按规范键去查 `WHERE sector = ?`：
                # 库里存的是原始写法，拿 "DEX" 查不到存成 "Dexes" 的行。
                global_counts = repo.canonical_sector_counts()
                wanted = {s for s in sector_counts if s}
                # 合并：DB 全库计数 + 当前批次 = 竞争度基准
                for sector, db_count in global_counts.items():
                    if sector not in wanted:
                        continue
                    sector_counts[sector] = sector_counts.get(sector, 0) + db_count
            except Exception as e:
                logger.warning(
                    "orchestrator.global_sector_counts_failed",
                    run_id=context.run_id,
                    error=str(e),
                    fallback="batch_only_counts",
                )

        # Process projects with bounded concurrency (ADR-007 Level 1)
        # Each project's exceptions are isolated — one failure never blocks others.
        async def _process_with_semaphore(project: RawProject, idx: int) -> PipelineState:
            async with self._semaphore:
                logger.info(
                    "orchestrator.project_start",
                    run_id=context.run_id,
                    project_id=project.id,
                    project_name=project.name,
                    progress=f"{idx + 1}/{len(projects)}",
                )
                try:
                    return await self._run_single_project(project, context, sector_counts)
                except Exception as e:
                    # Safety net: _run_single_project already catches, but if
                    # something escapes, don't let it kill the batch.
                    logger.error(
                        "orchestrator.project_unexpected_error",
                        project_id=project.id,
                        error=str(e),
                    )
                    state = PipelineState(project=project, context=context)
                    state.add_error(
                        AgentError(
                            agent_name="orchestrator",
                            kind="unexpected_error",
                            message=str(e),
                            project_id=project.id,
                        )
                    )
                    return state

        states: list[PipelineState] = await asyncio.gather(
            *(_process_with_semaphore(p, i) for i, p in enumerate(projects)),
            return_exceptions=False,  # exceptions are caught inside _run_single_project
        )
        errors: list[dict[str, str]] = []
        for state in states:
            for error in state.errors:
                errors.append(error.to_dict())

        # Calculate statistics
        elapsed_ms = (time.time() - start_time) * 1000
        scored_projects = [s for s in states if s.score is not None]
        top_score: int | None = None
        if scored_projects:
            top_score = max(cast(int, s.score) for s in scored_projects)

        # 先落库，再定状态。此前状态在持久化**之前**就算好了，于是"评分成功但一行都没
        # 写进去"依然返回 status=completed / error_count=0；上游 pipeline_run 又只看
        # state.score 就把 raw_projects 标成已处理，于是整批数据既没落库、也不再排队
        # 重试，而 DB 与 metrics 里都查不到任何痕迹。
        persisted_project_rows: list[dict[str, Any]] = []
        persist_failed = False
        if save_to_db and states:
            try:
                repo = ProjectRepository(economic_replay_enabled=settings.opportunity_economic_evidence_emit_enabled)
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
                    errors.append({"stage": "persist", "error": f"{missing} of {len(states)} rows were not persisted"})
                logger.info(
                    "orchestrator.db_save_complete",
                    run_id=context.run_id,
                    saved_count=len(persisted_project_rows),
                    total_count=len(states),
                )

        status: Literal["completed", "failed", "partial"]
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

    async def _run_agent_span(self, agent_name: str, project_id: str, coro: Awaitable[Any]) -> Any:
        """Wrap an agent coroutine with a named span."""
        with _tracing.tracer.start_as_current_span(f"airdrop.agent.{agent_name}") as span:
            span.set_attribute("project_id", project_id)
            try:
                return await coro
            except Exception as exc:
                end_span_with_error(span, exc)
                raise

    async def _run_agent(
        self,
        agent_name: str,
        project_id: str,
        coro: Awaitable[Any],
        output_ready: Callable[[], bool],
    ) -> Any:
        """Run an agent with per-agent metrics (duration + outcome).

        outcome（`app.metrics.record_agent_run`）三态：
        - error   = agent 抛异常（span 仍记 error，异常继续向上交给 gather 收集）
        - skipped = 正常返回但产出字段为 None（跑了但没有可输出结果）
        - success = 正常返回且产出非 None
        """
        start = time.time()
        try:
            result = await self._run_agent_span(agent_name, project_id, coro)
        except Exception:
            metrics.record_agent_run(agent=agent_name, result="error", duration_seconds=time.time() - start)
            raise
        outcome = "success" if output_ready() else "skipped"
        metrics.record_agent_run(agent=agent_name, result=outcome, duration_seconds=time.time() - start)
        return result

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

        with _tracing.tracer.start_as_current_span("airdrop.project") as span:
            span.set_attribute("project_id", project.id)
            span.set_attribute("project_name", project.name)
            span.set_attribute("run_id", context.run_id)

            try:
                # Stage 1: Run analysis agents in parallel
                logger.info(
                    "orchestrator.analysis_start",
                    project_id=project.id,
                    project_name=project.name,
                )

                # Stage 1a: 独立 agent 并行执行（Risk 依赖 Tokenomics 结果，故拆到 1b）
                stage1_results = await asyncio.gather(
                    self._run_agent(
                        "narrative", project.id, self.narrative.run(state), lambda: state.narrative is not None
                    ),
                    self._run_agent("team", project.id, self.team.run(state), lambda: state.team is not None),
                    self._run_agent(
                        "tokenomics", project.id, self.tokenomics.run(state), lambda: state.tokenomics is not None
                    ),
                    return_exceptions=True,
                )
                # Stage 1b: Tokenomics 就绪后再跑 Risk，保证 token_risk 用真实解锁数据
                risk_result = await asyncio.gather(
                    self._run_agent("risk", project.id, self.risk.run(state), lambda: state.risk is not None),
                    return_exceptions=True,
                )

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
                scorer_start = time.time()
                with _tracing.tracer.start_as_current_span("airdrop.agent.scorer") as scorer_span:
                    scorer_span.set_attribute("project_id", project.id)
                    try:
                        state = await scorer.run(state)
                    except Exception as exc:
                        end_span_with_error(scorer_span, exc)
                        metrics.record_agent_run(
                            agent="scorer", result="error", duration_seconds=time.time() - scorer_start
                        )
                        raise
                    metrics.record_agent_run(
                        agent="scorer",
                        result="success" if state.score is not None else "skipped",
                        duration_seconds=time.time() - scorer_start,
                    )
                    if state.score is not None:
                        scorer_span.set_attribute("score", state.score)
                        scorer_span.set_attribute("label", state.label or "")
                        metrics.record_project_score(state.score)

                # Mark completion
                state.completed_at = datetime.now(UTC)

                total_duration = (time.time() - state_start) * 1000
                span.set_attribute("score", state.score)
                span.set_attribute("label", state.label or "")
                span.set_attribute("duration_ms", total_duration)

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

                end_span_with_error(span, e)

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

        # 按**规范键**分组，不按原始写法。同一逻辑赛道在真实采集里有多种写法
        # （DefiLlama 给 "Dexes"、CryptoRank 给 "DEX"、github 推断给 "dex"），
        # 按原始写法分组会把一个赛道拆成好几组，每组计数偏小 → COMPETITION_MAP
        # 给出虚高的竞争度分。实测 12 个 DEX 项目分裂成 4 组后，competition
        # 从应有的 55 变成 75~100，等于把"赛道很挤"错报成"几乎没有竞品"。
        #
        # 只影响分组口径，不改写 project.sector（那个值参与确定性 ID）。
        for project in projects:
            key = canonical_sector_key(project.sector)
            if key:
                counts[key] = counts.get(key, 0) + 1

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
