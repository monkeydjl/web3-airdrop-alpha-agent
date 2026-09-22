"""DefiLlama free raises & fundraising mining service.

Leverages DefiLlama's 100% keyless, free public endpoints (/protocols and /protocol/{slug})
to extract comprehensive raises/funding data:
- rounds, amount, date, valuation
- lead investors & other investors (matching Tier-1 / Tier-2 VC rosters)
- treasury & audit signals

100% zero external commercial API fees, zero LLM token cost.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.services.funding import compute_funding_quality
from app.utils.normalize import normalize_name

logger = structlog.get_logger(__name__)

DEFILLAMA_BASE_URL = "https://api.llama.fi"


def parse_defillama_raises(raises_raw: list[dict[str, Any]]) -> dict[str, Any]:
    """Parse DefiLlama protocol['raises'] array into structured funding info."""
    if not raises_raw:
        return {
            "has_funding": False,
            "total_raised": 0.0,
            "funding_amount": 0.0,
            "funding_tier": "none",
            "round_count": 0,
            "rounds": [],
            "lead_investors": [],
            "investors": [],
            "last_round_date": None,
            "valuation": None,
            "funding_quality": 0.0,
        }

    total_amount_usd = 0.0
    rounds: list[str] = []
    lead_investors_set: set[str] = set()
    all_investors_set: set[str] = set()
    last_date_ts: int | None = None
    max_valuation: float | None = None

    for r in raises_raw:
        # Amount in DefiLlama is in millions USD (e.g. 5 = $5M, 0.5 = $500K)
        amt = r.get("amount")
        if amt is not None:
            try:
                amt_f = float(amt)
                if amt_f > 0:
                    total_amount_usd += amt_f * 1_000_000.0
            except (ValueError, TypeError):
                pass

        val = r.get("valuation")
        if val is not None:
            try:
                val_f = float(val)
                if val_f > 0:
                    val_usd = val_f * 1_000_000.0
                    if max_valuation is None or val_usd > max_valuation:
                        max_valuation = val_usd
            except (ValueError, TypeError):
                pass

        round_name = str(r.get("round") or "").strip()
        if round_name and round_name not in rounds:
            rounds.append(round_name)

        leads = r.get("leadInvestors") or []
        if isinstance(leads, list):
            for lead in leads:
                if lead and isinstance(lead, str):
                    lead_clean = lead.strip()
                    if lead_clean:
                        lead_investors_set.add(lead_clean)
                        all_investors_set.add(lead_clean)

        others = r.get("otherInvestors") or []
        if isinstance(others, list):
            for other in others:
                if other and isinstance(other, str):
                    other_clean = other.strip()
                    if other_clean:
                        all_investors_set.add(other_clean)

        d = r.get("date")
        if d is not None:
            try:
                d_ts = int(d)
                if last_date_ts is None or d_ts > last_date_ts:
                    last_date_ts = d_ts
            except (ValueError, TypeError):
                pass

    last_round_date_iso = None
    if last_date_ts:
        try:
            last_round_date_iso = datetime.fromtimestamp(last_date_ts, tz=UTC).strftime("%Y-%m-%d")
        except (OSError, ValueError, OverflowError):
            pass

    lead_investors = sorted(lead_investors_set)
    investors = sorted(all_investors_set)
    rounds_count = len(raises_raw)

    quality_res = compute_funding_quality(
        total_usd=total_amount_usd if total_amount_usd > 0 else None,
        rounds=rounds_count,
        last_date=last_round_date_iso,
        investors=investors,
        lead_investors=lead_investors,
    )

    return {
        "has_funding": True,
        "total_raised": total_amount_usd,
        "funding_amount": total_amount_usd,
        "funding_tier": quality_res.get("funding_tier", "unknown"),
        "funding_quality": quality_res.get("funding_quality", 0.0),
        "round_count": rounds_count,
        "rounds": rounds,
        "lead_investors": lead_investors,
        "investors": investors,
        "last_round_date": last_round_date_iso,
        "valuation": max_valuation,
    }


def build_protocols_slug_map(protocols: list[dict[str, Any]]) -> dict[str, str]:
    """Map name, normalized name, and slug to protocol slug."""
    slug_map: dict[str, str] = {}
    for p in protocols:
        slug = str(p.get("slug") or "").strip()
        name = str(p.get("name") or "").strip()
        if not slug:
            continue
        slug_lower = slug.lower()
        slug_map[slug_lower] = slug
        if name:
            slug_map[name.lower()] = slug
            norm = normalize_name(name)
            if norm:
                slug_map[norm.lower()] = slug
    return slug_map


def match_protocol_slug(project_name: str, slug_map: dict[str, str]) -> str | None:
    """Find best matching DefiLlama protocol slug for a project name."""
    if not project_name:
        return None
    raw = project_name.strip().lower()
    if raw in slug_map:
        return slug_map[raw]
    norm = normalize_name(project_name).lower()
    if norm in slug_map:
        return slug_map[norm]
    # Remove whitespace / hyphen
    simplified = raw.replace(" ", "").replace("-", "").replace("_", "")
    if simplified in slug_map:
        return slug_map[simplified]
    return None


async def fetch_protocol_funding(
    slug: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = 10.0,
) -> dict[str, Any] | None:
    """Fetch protocol details from DefiLlama and parse raises/funding data."""
    if not slug:
        return None
    url = f"{DEFILLAMA_BASE_URL}/protocol/{slug}"
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        own_client = True

    try:
        resp = await client.get(url)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None

        raises = data.get("raises") or []
        parsed = parse_defillama_raises(raises)
        parsed["slug"] = slug
        parsed["treasury"] = data.get("treasury")
        parsed["twitter"] = data.get("twitter")
        parsed["github"] = data.get("github")
        return parsed
    except Exception as exc:
        logger.warning("defillama.fetch_protocol_funding_failed", slug=slug, error=str(exc))
        return None
    finally:
        if own_client:
            await client.aclose()


async def fetch_all_protocols(
    client: httpx.AsyncClient | None = None,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Fetch the full protocols list from DefiLlama to build index."""
    url = f"{DEFILLAMA_BASE_URL}/protocols"
    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        own_client = True

    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        return []
    except Exception as exc:
        logger.warning("defillama.fetch_all_protocols_failed", error=str(exc))
        return []
    finally:
        if own_client:
            await client.aclose()
