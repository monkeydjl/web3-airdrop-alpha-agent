"""Single project comprehensive re-evaluation service.

Orchestrates full re-evaluation for a single project:
1. Loads current project row and metadata from DB;
2. Restores saved signals and infers airdrop flags;
3. Runs 8-dimensional scoring agents via SimpleOrchestrator;
4. Persists the updated state, updates dedup_keys, and records project_history snapshot;
5. Evaluates OpportunityAssessment (viability gate, anti-PUA, capital friction, economics);
6. Returns canonical updated project dictionary with full evaluation projections.
"""

from __future__ import annotations

from typing import Any
import structlog

from app.agents.base import AgentContext, RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import SimpleOrchestrator, global_sector_counts
from app.opportunity.service import OpportunityService
from app.repository import ProjectRepository
from app.services.project_signals import apply_signals_to_kwargs

logger = structlog.get_logger(__name__)


async def evaluate_single_project(project_id: str) -> dict[str, Any]:
    """Perform a full re-evaluation of a single project and persist results."""
    repo = ProjectRepository()
    row = repo.get_by_id(project_id)
    if not row:
        raise ValueError(f"Project not found: {project_id}")

    name = row.get("name") or ""
    sector = row.get("sector")
    stage = row.get("stage") or "mainnet"
    source = row.get("source") or "unknown"

    # 1. Restore saved signals and infer flags
    saved = apply_signals_to_kwargs(row.get("meta"))
    flags = CollectorAgent._infer_airdrop_flags(
        source.split(",")[0] if source else "defillama",
        {
            "name": name,
            "sector": sector,
            "stage": stage,
            "url": row.get("url"),
            **{k: v for k, v in saved.items() if v not in (None, "", [], "unknown")},
        },
    )
    merged = {**flags, **saved}
    for k in ("has_testnet", "has_points_program", "no_token_yet", "recent_funding"):
        if k in saved:
            merged[k] = saved[k]
        elif k in flags:
            merged[k] = flags[k]

    # Only pass known RawProject fields
    field_names = {field.name for field in RawProject.__dataclass_fields__.values()}
    raw_kwargs = {
        "id": project_id,
        "name": name,
        "url": row.get("url"),
        "sector": sector,
        "stage": stage,
        "source": source,
        "auto_discovered": True,
        **{k: v for k, v in merged.items() if k in field_names},
    }
    raw_project = RawProject(**raw_kwargs)

    # 2. Run 8-dimension analysis orchestrator
    orch = SimpleOrchestrator()
    ctx = AgentContext(run_id="single-project-eval")
    counts = global_sector_counts(fallback=[raw_project])
    state = await orch._run_single_project(raw_project, ctx, counts)

    # 3. Persist pipeline state (updates projects table + writes project_history snapshot)
    repo.save(state)

    # 4. Evaluate Opportunity assessment (Viability Gate, Anti-PUA, Economics)
    try:
        with OpportunityService() as opp_service:
            opp_service.evaluate(project_id, persist=True)
    except Exception as exc:
        logger.warning(
            "project.evaluation_opportunity_failed",
            project_id=project_id,
            error=str(exc),
        )

    # 5. Reload canonical updated row
    updated_row = repo.get_by_id(project_id)
    if not updated_row:
        raise RuntimeError(f"Failed to reload updated project: {project_id}")

    logger.info(
        "project.evaluated",
        project_id=project_id,
        name=name,
        score=state.score,
        label=state.label,
    )
    return updated_row
