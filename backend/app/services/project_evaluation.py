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

import asyncio
import uuid
from typing import Any

import structlog

from app.agents.base import AgentContext, RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import SimpleOrchestrator, global_sector_counts
from app.config import settings
from app.opportunity.service import OpportunityService
from app.repository import ProjectRepository
from app.services.project_signals import apply_signals_to_kwargs

logger = structlog.get_logger(__name__)


async def evaluate_single_project(project_id: str) -> dict[str, Any]:
    """Perform a full re-evaluation of a single project and persist results."""
    repo = ProjectRepository()
    row = await asyncio.to_thread(repo.get_by_id, project_id)
    if not row:
        raise ValueError(f"Project not found: {project_id}")

    name = row.get("name") or ""
    sector = row.get("sector")
    stage = row.get("stage") or "mainnet"
    source = row.get("source") or "unknown"

    # 1. Restore saved signals and infer flags
    saved = apply_signals_to_kwargs(row.get("meta"))
    inferred_signal_keys = {
        "explicit_airdrop_mention",
        "explicit_no_airdrop",
        "has_points_program",
        "explicit_points_program",
        "has_testnet",
        "has_task_portal",
        "token_launch_confirmed",
    }
    input_signals = {
        k: v for k, v in saved.items() if v not in (None, "", [], "unknown") and k not in inferred_signal_keys
    }
    flags = CollectorAgent._infer_airdrop_flags(
        source.split(",")[0] if source else "defillama",
        {
            "name": name,
            "sector": sector,
            "stage": stage,
            "url": row.get("url"),
            **input_signals,
        },
    )
    merged = {**saved, **flags}
    for k in ("has_testnet", "has_points_program", "explicit_points_program", "recent_funding"):
        if flags.get(k) is True:
            merged[k] = True
        elif k in flags and flags[k] is not None:
            merged[k] = flags[k]
        elif k in saved and saved[k] is not None:
            merged[k] = saved[k]

    # no_token_yet / token_launch_confirmed: 既有库内明确标注已发币的，必须严格保留
    if saved.get("no_token_yet") is False:
        merged["no_token_yet"] = False
    elif "no_token_yet" in flags:
        merged["no_token_yet"] = flags["no_token_yet"]
    if saved.get("token_launch_confirmed") is True or flags.get("token_launch_confirmed") is True:
        merged["token_launch_confirmed"] = True

    # 否认一旦写入就保持：重算时正文未必还带那句原话，False 覆盖会把
    # 已否决的项目放回 FARM。文本没再说，不代表官方改口了。
    if saved.get("explicit_no_airdrop") is True or flags.get("explicit_no_airdrop") is True:
        merged["explicit_no_airdrop"] = True

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
    ctx = AgentContext(
        run_id=f"single-project-eval-{uuid.uuid4().hex[:8]}",
        enable_llm=settings.is_llm_enabled,
    )
    counts = await asyncio.to_thread(global_sector_counts, fallback=[raw_project])
    state = await orch._run_single_project(raw_project, ctx, counts)

    # 3. Persist pipeline state + Opportunity assessment off event loop
    def _persist_and_reload() -> dict[str, Any] | None:
        repo.save(state)
        try:
            with OpportunityService() as opp_service:
                opp_service.evaluate(project_id, persist=True)
        except Exception as exc:
            logger.warning(
                "project.evaluation_opportunity_failed",
                project_id=project_id,
                error=str(exc),
            )
        return repo.get_by_id(project_id)

    updated_row = await asyncio.to_thread(_persist_and_reload)
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
