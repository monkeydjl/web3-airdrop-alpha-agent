"""Sync DefiLlama Free Raises & Fundraising into Database.

Matches projects in `projects` table against DefiLlama protocols,
fetches keyless raises data from `https://api.llama.fi/protocol/{slug}`,
and enriches `funding` (amount, tier, rounds, investors, last date).
Also re-evaluates `viability_gate.py` to upgrade falsely unviable projects.

Usage:
    backend/venv/Scripts/python.exe backend/scripts/sync_defillama_raises.py              # dry-run
    backend/venv/Scripts/python.exe backend/scripts/sync_defillama_raises.py --apply      # persist to db
    backend/venv/Scripts/python.exe backend/scripts/sync_defillama_raises.py --limit 10   # test with first 10
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from app.config import settings

if not Path(settings.db_path).is_absolute():
    backend_db = BACKEND_DIR / settings.db_path
    if backend_db.exists():
        settings.db_path = str(backend_db)

from app.db import dict_from_row, get_connection
from app.services.defillama_raises import (
    build_protocols_slug_map,
    fetch_all_protocols,
    fetch_protocol_funding,
    match_protocol_slug,
)
from app.services.project_signals import funding_public_view, parse_meta
from app.services.viability_gate import evaluate_project_viability


async def run_sync_defillama_raises(
    *,
    apply_changes: bool = False,
    limit: int = 0,
) -> dict[str, Any]:
    """Sync DefiLlama raises for existing projects in SQLite."""
    conn = get_connection()
    now = datetime.now(UTC)

    print(f"[{now.strftime('%H:%M:%S')}] Fetching DefiLlama protocols index...")
    async with httpx.AsyncClient(timeout=15.0) as client:
        protocols = await fetch_all_protocols(client=client)
        if not protocols:
            print("[ERROR] Failed to fetch protocols list from DefiLlama.")
            return {"ok": False, "error": "protocols_fetch_failed"}

        print(f"[{now.strftime('%H:%M:%S')}] Loaded {len(protocols)} protocols from DefiLlama. Building slug map...")
        slug_map = build_protocols_slug_map(protocols)

        # Load projects
        cursor = conn.execute("SELECT id, name, sector, stage, score, label, reason, meta FROM projects ORDER BY score DESC")
        rows = cursor.fetchall()
        if limit > 0:
            rows = rows[:limit]

        print(f"[{now.strftime('%H:%M:%S')}] Scanning {len(rows)} projects in database...")

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

            # Match slug
            matched_slug = match_protocol_slug(name, slug_map)
            if not matched_slug:
                continue

            matched_protocols += 1
            # Fetch funding from protocol endpoint
            proto_funding = await fetch_protocol_funding(matched_slug, client=client)
            if not proto_funding or not proto_funding.get("has_funding"):
                continue

            new_amount = proto_funding.get("funding_amount", 0.0)
            existing_amount = existing_funding.get("funding_total_usd") or 0.0
            new_investors = proto_funding.get("investors") or []
            new_tier = proto_funding.get("funding_tier", "unknown")

            # Check if this brings better or new funding info
            is_improvement = (
                (new_amount > existing_amount)
                or (not existing_funding.get("funding_investors") and bool(new_investors))
                or (existing_funding.get("funding_tier") in (None, "none", "unknown") and new_tier in ("tier1", "tier2", "tier3"))
            )

            if not is_improvement:
                continue

            enriched_funding_count += 1

            # Merge safely: keep higher amount, union investors, choose best tier
            final_amount = max(new_amount, existing_amount)
            final_investors = list(dict.fromkeys([*existing_funding.get("funding_investors", []), *new_investors]))
            final_leads = list(dict.fromkeys([*existing_funding.get("funding_lead_investors", []), *proto_funding.get("lead_investors", [])]))
            final_tier = (
                "tier1"
                if "tier1" in (new_tier, existing_funding.get("funding_tier"))
                else (
                    "tier2"
                    if "tier2" in (new_tier, existing_funding.get("funding_tier"))
                    else (new_tier if new_tier != "unknown" else existing_funding.get("funding_tier") or "unknown")
                )
            )

            # Prepare enriched funding block
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

            # Re-evaluate viability
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

            print(
                f"  -> [{name}] (slug: {matched_slug}): ${existing_amount:,.0f} -> ${new_amount:,.0f} "
                f"({existing_funding.get('funding_tier')} -> {new_tier}) | viability: {old_viability} -> {new_viability}"
            )

            if apply_changes:
                # Update meta
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
            print(f"\n[APPLIED] Successfully updated {enriched_funding_count} projects in database.")
        else:
            print(f"\n[DRY-RUN] Preview complete. {enriched_funding_count} projects can be enriched (run with --apply to commit).")

        return {
            "ok": True,
            "total_scanned": len(rows),
            "matched_protocols": matched_protocols,
            "enriched_funding_count": enriched_funding_count,
            "viability_upgraded_count": viability_upgraded_count,
            "details": details,
            "applied": apply_changes,
        }


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync DefiLlama raises and funding into projects database")
    parser.add_argument("--apply", action="store_true", help="Apply changes to SQLite database")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of projects to scan (0 = all)")
    args = parser.parse_args()

    asyncio.run(run_sync_defillama_raises(apply_changes=args.apply, limit=args.limit))


if __name__ == "__main__":
    main()
