"""Manual funding edit + optional rescore."""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Query
from pydantic import BaseModel, Field

from app.agents.base import AgentContext, RawProject
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.repository import ProjectRepository
from app.services.funding import compute_funding_quality
from app.services.project_signals import (
    apply_signals_to_kwargs,
    funding_public_view,
    parse_meta,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["funding"])


class FundingUpdate(BaseModel):
    funding_total_usd: float | None = Field(None, description="累计融资 USD")
    funding_rounds: int | None = Field(None, ge=0, description="轮次数")
    funding_last_date: str | None = Field(None, description="最近一轮日期 YYYY-MM-DD")
    funding_investors: list[str] | None = Field(None, description="投资方列表")
    funding_lead_investors: list[str] | None = Field(None, description="领投方")
    recent_funding: bool | None = Field(None, description="是否视为近期融资")
    note: str | None = Field(None, description="备注（存 meta）")


def _row_to_raw_project(row: dict[str, Any]) -> RawProject:
    sig = apply_signals_to_kwargs(row.get("meta"))
    return RawProject(
        id=row["id"],
        name=row.get("name") or "",
        url=row.get("url"),
        sector=row.get("sector"),
        stage=row.get("stage"),
        source=row.get("source") or "manual",
        **sig,
    )


@router.get("/projects/{project_id}/funding")
async def get_funding(project_id: str = Path(...)):
    repo = ProjectRepository()
    row = repo.get_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "project not found"})
    funding = funding_public_view(row.get("meta"))
    meta = parse_meta(row.get("meta"))
    return {
        "ok": True,
        "data": {
            "project_id": project_id,
            "funding": funding,
            "funding_note": meta.get("funding_note"),
        },
    }


@router.patch("/projects/{project_id}/funding")
async def patch_funding(
    project_id: str = Path(...),
    body: FundingUpdate = ...,
    rescore: bool = Query(True, description="保存后是否立即重算评分"),
):
    """Save manual funding fields into meta.signals and optionally rescore."""
    repo = ProjectRepository()
    row = repo.get_by_id(project_id)
    if not row:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "project not found"})

    existing = funding_public_view(row.get("meta"))
    investors = (
        body.funding_investors if body.funding_investors is not None else existing.get("funding_investors") or []
    )
    leads = (
        body.funding_lead_investors
        if body.funding_lead_investors is not None
        else existing.get("funding_lead_investors") or []
    )
    total = body.funding_total_usd if body.funding_total_usd is not None else existing.get("funding_total_usd")
    rounds = body.funding_rounds if body.funding_rounds is not None else int(existing.get("funding_rounds") or 0)
    last_date = body.funding_last_date if body.funding_last_date is not None else existing.get("funding_last_date")
    recent_flag = body.recent_funding if body.recent_funding is not None else bool(existing.get("recent_funding"))
    if total and float(total) > 0:
        recent_flag = True

    computed = compute_funding_quality(
        total_usd=float(total) if total is not None else None,
        rounds=int(rounds or 0),
        last_date=last_date,
        investors=list(investors),
        lead_investors=list(leads),
        recent_funding_flag=recent_flag,
    )

    signals: dict[str, Any] = {
        "funding_total_usd": computed["funding_total_usd"],
        "funding_rounds": computed["funding_rounds"],
        "funding_last_date": computed["funding_last_date"],
        "funding_investors": computed["funding_investors"],
        "funding_lead_investors": computed["funding_lead_investors"],
        "funding_tier": computed["funding_tier"],
        "funding_quality": computed["funding_quality"],
        "recent_funding": bool(recent_flag or (computed["funding_quality"] or 0) > 0.2),
    }

    updated = repo.update_meta_signals(project_id, signals)
    if not updated:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "project not found"})

    if body.note is not None:
        meta = parse_meta(updated.get("meta"))
        meta["funding_note"] = body.note
        # re-write note via signals merge path
        conn_meta = json_dumps_meta(meta)
        from datetime import UTC, datetime

        from app.db import get_connection

        conn = get_connection()
        try:
            conn.execute(
                "UPDATE projects SET meta = ?, updated_at = ? WHERE id = ?",
                (conn_meta, datetime.now(UTC), project_id),
            )
            conn.commit()
            updated["meta"] = conn_meta
        finally:
            conn.close()

    score_result = None
    if rescore:
        try:
            project = _row_to_raw_project(updated)
            orch = SimpleOrchestrator()
            ctx = AgentContext(run_id="funding-edit")
            counts = orch._calculate_sector_counts([project])
            state = await orch._run_single_project(project, ctx, counts)
            repo.save(state)
            score_result = {
                "score": state.score,
                "label": state.label,
                "confidence": state.confidence,
                "reason": state.reason,
            }
        except Exception as e:
            logger.error("funding.rescore_failed", project_id=project_id, error=str(e))
            score_result = {"error": str(e)}

    logger.info(
        "funding.updated",
        project_id=project_id,
        tier=signals["funding_tier"],
        quality=signals["funding_quality"],
        rescored=bool(rescore),
    )
    return {
        "ok": True,
        "data": {
            "project_id": project_id,
            "funding": funding_public_view(updated.get("meta")),
            "score": score_result,
        },
    }


def json_dumps_meta(meta: dict) -> str:
    import json

    return json.dumps(meta, ensure_ascii=False)
