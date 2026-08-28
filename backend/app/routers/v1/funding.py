"""Manual funding edit + optional rescore."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Body, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field

from app.agents.base import AgentContext, RawProject
from app.agents.orchestrator_simple import SimpleOrchestrator, global_sector_counts
from app.repository import ProjectRepository
from app.services.funding import _parse_date, compute_funding_quality
from app.services.project_signals import (
    apply_signals_to_kwargs,
    funding_public_view,
    parse_meta,
)

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["funding"])


class FundingUpdate(BaseModel):
    # allow_inf_nan=False：此前 {"funding_total_usd": NaN} 会先把非法 JSON
    # （字面量 NaN）提交进 projects.meta，再以 500 告诉调用方"写失败了"——
    # 实际已经写进去了，且 Postgres 的 jsonb 会硬拒。interactions/opportunity
    # 两个模型本来就设了这个开关，这里对齐。
    model_config = ConfigDict(allow_inf_nan=False)

    funding_total_usd: float | None = Field(None, ge=0, description="累计融资 USD")
    funding_rounds: int | None = Field(None, ge=0, le=100, description="轮次数")
    funding_last_date: str | None = Field(None, max_length=32, description="最近一轮日期 YYYY-MM-DD")
    funding_investors: list[str] | None = Field(None, max_length=200, description="投资方列表")
    funding_lead_investors: list[str] | None = Field(None, max_length=50, description="领投方")
    recent_funding: bool | None = Field(None, description="是否视为近期融资")
    note: str | None = Field(None, max_length=2000, description="备注（存 meta）")


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
def get_funding(project_id: str = Path(...)) -> dict[str, Any]:
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
    body: FundingUpdate = Body(...),  # noqa: B008 - FastAPI 惯用写法
    rescore: bool = Query(True, description="保存后是否立即重算评分"),
) -> dict[str, Any]:
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
    # recent_funding 会流进 airdrop_signal(+5 加成)与 team("recent funding" flag)，
    # 且这两处都不看日期。此前只要 total>0 就无条件置 True——既覆盖了用户显式传入
    # 的 recent_funding=False(用户明说"不算近期"也被改回)，又把 2021 年的老轮次标成
    # 近期。改为：用户显式指定则一律尊重；未指定时才按 last_date 时效推断，已知且
    # 距今 >365 天不算近期，日期未知则沿用"有融资额即视为近期"的保守默认。
    if body.recent_funding is not None:
        recent_flag = body.recent_funding
    else:
        recent_flag = bool(existing.get("recent_funding"))
        if total and float(total) > 0:
            dt = _parse_date(last_date)
            recent_flag = dt is None or (datetime.now(UTC) - dt).days <= 365

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

    # note 通过 meta_updates 在同一事务内随 signals 一起写入：此前 note 另开一条
    # 连接、用读时刻的 meta 快照整体覆盖，与 signals 写非同一事务，并发下会丢写、
    # 且第二次失败时 signals 已提交而 note 丢失。合并为单次原子写消除该窗口。
    meta_updates = {"funding_note": body.note} if body.note is not None else None
    updated = repo.update_meta_signals(project_id, signals, meta_updates=meta_updates)
    if not updated:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "project not found"})

    score_result = None
    if rescore:
        try:
            project = _row_to_raw_project(updated)
            orch = SimpleOrchestrator()
            ctx = AgentContext(run_id="funding-edit")
            # 单项目重算必须用全库赛道计数：只数这一个项目会得到 {sector: 1}
            # → 竞争度满分 100，同一项目在批量评分里可能只有 40，凭空多出 6 分。
            counts = global_sector_counts(fallback=[project])
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
