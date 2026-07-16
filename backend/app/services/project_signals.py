"""Pack / unpack extended project signals into projects.meta JSON.

Keeps scoring inputs (funding, docs, task portal, etc.) across rescore
without requiring a wide column migration.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import RawProject

# Fields stored under meta["signals"]
SIGNAL_KEYS = (
    "has_testnet",
    "has_points_program",
    "no_token_yet",
    "recent_funding",
    "has_docs",
    "has_whitepaper",
    "has_roadmap",
    "has_github",
    "has_twitter",
    "has_discord",
    "github_stars",
    "github_recent_push_days",
    "explicit_airdrop_mention",
    "tvl_usd",
    "description",
    "has_task_portal",
    "has_contract",
    "source_count",
    "roadmap_delivery",
    "sybil_friction",
    "funding_total_usd",
    "funding_rounds",
    "funding_last_date",
    "funding_investors",
    "funding_lead_investors",
    "funding_tier",
    "funding_quality",
)


def parse_meta(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def signals_from_project(project: RawProject) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SIGNAL_KEYS:
        if hasattr(project, key):
            val = getattr(project, key)
            if key in ("funding_investors", "funding_lead_investors"):
                out[key] = list(val or [])
            else:
                out[key] = val
    return out


def merge_meta(existing: Any, project: RawProject) -> str:
    """Merge project signals into meta JSON string for DB storage."""
    meta = parse_meta(existing)
    prev = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    new_sig = signals_from_project(project)
    # Prefer non-empty / more informative values from project
    merged = dict(prev)
    for k, v in new_sig.items():
        if (
            (v is None or v == "" or v == [] or v == 0 or v == "unknown")
            and k in prev
            and prev[k] not in (None, "", [], 0, "unknown", "none")
        ):
            # keep previous if new is empty default
            continue
        merged[k] = v
    meta["signals"] = merged
    return json.dumps(meta, ensure_ascii=False)


def apply_signals_to_kwargs(meta: Any) -> dict[str, Any]:
    """Extract kwargs for RawProject construction from meta."""
    signals = parse_meta(meta).get("signals") or {}
    if not isinstance(signals, dict):
        return {}
    kwargs: dict[str, Any] = {}
    for key in SIGNAL_KEYS:
        if key not in signals:
            continue
        kwargs[key] = signals[key]
    # types
    if "github_stars" in kwargs:
        try:
            kwargs["github_stars"] = int(kwargs["github_stars"] or 0)
        except (TypeError, ValueError):
            kwargs["github_stars"] = 0
    if "funding_rounds" in kwargs:
        try:
            kwargs["funding_rounds"] = int(kwargs["funding_rounds"] or 0)
        except (TypeError, ValueError):
            kwargs["funding_rounds"] = 0
    if "funding_quality" in kwargs:
        try:
            kwargs["funding_quality"] = float(kwargs["funding_quality"] or 0)
        except (TypeError, ValueError):
            kwargs["funding_quality"] = 0.0
    if "source_count" in kwargs:
        try:
            kwargs["source_count"] = max(1, int(kwargs["source_count"] or 1))
        except (TypeError, ValueError):
            kwargs["source_count"] = 1
    for list_key in ("funding_investors", "funding_lead_investors"):
        if list_key in kwargs and not isinstance(kwargs[list_key], list):
            if isinstance(kwargs[list_key], str):
                kwargs[list_key] = [x.strip() for x in kwargs[list_key].split(",") if x.strip()]
            else:
                kwargs[list_key] = []
    return kwargs


def funding_public_view(meta: Any) -> dict[str, Any]:
    """API-facing funding block from meta.signals."""
    s = parse_meta(meta).get("signals") or {}
    if not isinstance(s, dict):
        s = {}
    return {
        "funding_total_usd": s.get("funding_total_usd"),
        "funding_rounds": s.get("funding_rounds") or 0,
        "funding_last_date": s.get("funding_last_date"),
        "funding_investors": s.get("funding_investors") or [],
        "funding_lead_investors": s.get("funding_lead_investors") or [],
        "funding_tier": s.get("funding_tier") or "unknown",
        "funding_quality": s.get("funding_quality") or 0,
        "recent_funding": bool(s.get("recent_funding")),
    }
