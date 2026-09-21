"""Ops database maintenance tasks.

Provides database-level batch tasks:
1. `sync_database_defillama_raises`: Fetch free raises data from DefiLlama protocol endpoints and enrich projects.
2. `audit_database_viability`: Run full database audit on project viability gates (points machine, low funding, runway depleted).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.db import dict_from_row, get_connection
from app.opportunity.decision import LOW_RUNWAY_RISK
from app.services.defillama_raises import (
    build_protocols_slug_map,
    fetch_all_protocols,
    fetch_protocol_funding,
    match_protocol_slug,
)
from app.services.project_signals import funding_public_view, parse_meta
from app.services.viability_gate import (
    LOW_FUNDING_UNVIABLE,
    RUNWAY_DEPLETED,
    UNBACKED_POINTS_MACHINE,
    evaluate_project_viability,
)

logger = structlog.get_logger(__name__)


async def sync_database_defillama_raises(
    *,
    apply_changes: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Sync DefiLlama raises for existing projects in SQLite/Postgres.

    Args:
        apply_changes: If True, commits updates to database. If False, runs in dry-run preview mode.
        limit: Max projects to inspect (0 = all).

    Returns:
        Structured summary with counts and enriched project details.
    """
    conn = get_connection()
    now = datetime.now(UTC)

    logger.info("ops.sync_funding.started", apply_changes=apply_changes, limit=limit)

    async with httpx.AsyncClient(timeout=15.0) as client:
        protocols = await fetch_all_protocols(client=client)
        if not protocols:
            logger.error("ops.sync_funding.protocols_fetch_failed")
            return {"ok": False, "error": "protocols_fetch_failed"}

        slug_map = build_protocols_slug_map(protocols)

        cursor = conn.execute(
            "SELECT id, name, sector, stage, score, label, reason, meta FROM projects ORDER BY score DESC"
        )
        rows = cursor.fetchall()
        if limit > 0:
            rows = rows[:limit]

        matched_protocols = 0
        enriched_funding_count = 0
        viability_upgraded_count = 0
        details: list[dict[str, Any]] = []

        for row in rows:
            p = dict_from_row(row)
            project_id = str(p["id"])
            name = str(p.get("name") or project_id)
            meta = parse_meta(p.get("meta"))
            existing_funding = funding_public_view(meta)

            matched_slug = match_protocol_slug(name, slug_map)
            if not matched_slug:
                continue

            matched_protocols += 1
            proto_funding = await fetch_protocol_funding(matched_slug, client=client)
            if not proto_funding or not proto_funding.get("has_funding"):
                continue

            new_amount = proto_funding.get("funding_amount", 0.0)
            existing_amount = existing_funding.get("funding_total_usd") or 0.0
            new_investors = proto_funding.get("investors") or []
            new_tier = proto_funding.get("funding_tier", "unknown")

            is_improvement = (
                (new_amount > existing_amount)
                or (not existing_funding.get("funding_investors") and bool(new_investors))
                or (
                    existing_funding.get("funding_tier") in (None, "none", "unknown")
                    and new_tier in ("tier1", "tier2", "tier3")
                )
            )

            if not is_improvement:
                continue

            enriched_funding_count += 1

            final_amount = max(new_amount, existing_amount)
            final_investors = list(
                dict.fromkeys([*existing_funding.get("funding_investors", []), *new_investors])
            )
            final_leads = list(
                dict.fromkeys(
                    [*existing_funding.get("funding_lead_investors", []), *proto_funding.get("lead_investors", [])]
                )
            )
            final_tier = (
                "tier1"
                if "tier1" in (new_tier, existing_funding.get("funding_tier"))
                else (
                    "tier2"
                    if "tier2" in (new_tier, existing_funding.get("funding_tier"))
                    else (new_tier if new_tier != "unknown" else existing_funding.get("funding_tier") or "unknown")
                )
            )

            enriched_funding = {
                "funding_amount": final_amount,
                "funding_total_usd": final_amount,
                "funding_tier": final_tier,
                "funding_quality": proto_funding.get("funding_quality", 0.0),
                "round_count": max(proto_funding.get("round_count", 0), existing_funding.get("funding_rounds") or 0),
                "funding_rounds": max(proto_funding.get("round_count", 0), existing_funding.get("funding_rounds") or 0),
                "rounds": proto_funding.get("rounds", []),
                "lead_investors": final_leads,
                "funding_lead_investors": final_leads,
                "investors": final_investors,
                "funding_investors": final_investors,
                "last_round_date": proto_funding.get("last_round_date") or existing_funding.get("funding_last_date"),
                "funding_last_date": proto_funding.get("last_round_date") or existing_funding.get("funding_last_date"),
                "valuation": proto_funding.get("valuation") or existing_funding.get("valuation"),
                "source": "defillama",
                "synced_at": now.isoformat(),
            }

            signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
            old_viability = meta.get("viability_tier") or "unknown"
            viability_eval = evaluate_project_viability(
                funding_total_usd=new_amount,
                funding_tier=new_tier,
                funding_rounds=proto_funding.get("round_count", 0),
                funding_last_date=proto_funding.get("last_round_date"),
                funding_investors=new_investors,
                funding_lead_investors=proto_funding.get("lead_investors", []),
                github_inactive_days=signals.get("github_recent_push_days"),
                tvl_usd=signals.get("tvl_usd"),
                has_points_program=bool(signals.get("has_points_program")),
            )
            new_viability = viability_eval.get("tier", "viable")
            if old_viability == "unviable" and new_viability in ("viable", "borderline"):
                viability_upgraded_count += 1

            detail_entry = {
                "id": project_id,
                "name": name,
                "slug": matched_slug,
                "old_amount": existing_amount,
                "new_amount": new_amount,
                "old_tier": existing_funding.get("funding_tier"),
                "new_tier": new_tier,
                "investors": new_investors[:5],
                "old_viability": old_viability,
                "new_viability": new_viability,
            }
            details.append(detail_entry)

            if apply_changes:
                meta["funding"] = enriched_funding
                meta["signals"] = {**signals, **enriched_funding}
                meta["viability_tier"] = new_viability
                meta["viability_advisory"] = viability_eval.get("recommendation_zh")
                meta_json = json.dumps(meta, ensure_ascii=False)

                conn.execute(
                    "UPDATE projects SET meta = ?, updated_at = ? WHERE id = ?",
                    (meta_json, now.isoformat(), project_id),
                )

        if apply_changes:
            conn.commit()

        result = {
            "ok": True,
            "total_scanned": len(rows),
            "matched_protocols": matched_protocols,
            "enriched_funding_count": enriched_funding_count,
            "viability_upgraded_count": viability_upgraded_count,
            "details": details,
            "applied": apply_changes,
        }
        logger.info(
            "ops.sync_funding.completed",
            total_scanned=len(rows),
            enriched=enriched_funding_count,
            upgraded=viability_upgraded_count,
            applied=apply_changes,
        )
        return result


def audit_database_viability(*, apply_changes: bool = False) -> dict[str, Any]:
    """Audit project viability and runway health across all projects in the database.

    Args:
        apply_changes: If True, commits updates and label downgrades to database.

    Returns:
        Structured audit report with tier counts, reasons, and downgraded projects.
    """
    conn = get_connection()
    now = datetime.now(UTC)

    logger.info("ops.audit_viability.started", apply_changes=apply_changes)

    try:
        cursor = conn.execute(
            "SELECT id, name, sector, stage, score, label, reason, meta FROM projects ORDER BY score DESC"
        )
        rows = cursor.fetchall()

        total = len(rows)
        tier_counts = {"viable": 0, "borderline": 0, "unviable": 0}
        reason_counts = {
            UNBACKED_POINTS_MACHINE: 0,
            LOW_FUNDING_UNVIABLE: 0,
            RUNWAY_DEPLETED: 0,
        }
        downgraded_projects: list[dict[str, Any]] = []

        for row in rows:
            p = dict_from_row(row)
            project_id = str(p["id"])
            name = str(p.get("name") or project_id)
            current_label = str(p.get("label") or "WATCH")
            raw_reason = p.get("reason")
            reasons_list: list[str] = (
                json.loads(raw_reason)
                if isinstance(raw_reason, str) and raw_reason.startswith("[")
                else ([str(raw_reason)] if raw_reason else [])
            )

            meta = parse_meta(p.get("meta"))
            signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
            funding = funding_public_view(meta)

            funding_total_usd = signals.get("funding_total_usd") or funding.get("funding_total_usd")
            funding_tier = signals.get("funding_tier") or funding.get("funding_tier")
            funding_rounds = signals.get("funding_rounds") or funding.get("funding_rounds") or 0
            funding_last_date = signals.get("funding_last_date") or funding.get("funding_last_date")
            funding_investors = signals.get("funding_investors") or funding.get("funding_investors") or []
            funding_lead_investors = (
                signals.get("funding_lead_investors") or funding.get("funding_lead_investors") or []
            )
            github_inactive_days = signals.get("github_recent_push_days")
            tvl_usd = signals.get("tvl_usd")
            has_points_program = bool(signals.get("has_points_program"))
            stage = str(p.get("stage") or "ideation")

            res = evaluate_project_viability(
                funding_total_usd=float(funding_total_usd) if funding_total_usd is not None else None,
                funding_tier=str(funding_tier) if funding_tier else None,
                funding_rounds=int(funding_rounds) if funding_rounds else 0,
                funding_last_date=str(funding_last_date) if funding_last_date else None,
                funding_investors=list(funding_investors) if isinstance(funding_investors, (list, tuple)) else [],
                funding_lead_investors=list(funding_lead_investors)
                if isinstance(funding_lead_investors, (list, tuple))
                else [],
                github_inactive_days=int(github_inactive_days) if github_inactive_days is not None else None,
                tvl_usd=float(tvl_usd) if tvl_usd is not None else None,
                has_points_program=has_points_program,
                stage=stage,
                now=now,
            )

            tier = res["tier"]
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            for r in res["reasons"]:
                reason_counts[r] = reason_counts.get(r, 0) + 1

            new_label = current_label
            if current_label == "FARM" and tier == "unviable":
                new_label = "IGNORE" if UNBACKED_POINTS_MACHINE in res["reasons"] else "WATCH"

                if LOW_RUNWAY_RISK not in reasons_list:
                    reasons_list.append(LOW_RUNWAY_RISK)

                downgraded_projects.append(
                    {
                        "id": project_id,
                        "name": name,
                        "from_label": current_label,
                        "to_label": new_label,
                        "reasons": list(res["reasons"]),
                        "reasons_zh": list(res["reasons_zh"]),
                    }
                )

            if apply_changes:
                meta["viability_tier"] = tier
                meta["viability_advisory"] = res
                meta_json = json.dumps(meta, ensure_ascii=False)
                reason_json = json.dumps(reasons_list, ensure_ascii=False)

                conn.execute(
                    """
                    UPDATE projects
                    SET label = ?, reason = ?, meta = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (new_label, reason_json, meta_json, now.isoformat(), project_id),
                )

        if apply_changes:
            conn.commit()

        result = {
            "ok": True,
            "total_scanned": total,
            "tier_counts": tier_counts,
            "reason_counts": reason_counts,
            "downgraded_count": len(downgraded_projects),
            "downgraded_projects": downgraded_projects,
            "applied": apply_changes,
        }
        logger.info(
            "ops.audit_viability.completed",
            total_scanned=total,
            downgraded=len(downgraded_projects),
            applied=apply_changes,
        )
        return result

    finally:
        conn.close()
