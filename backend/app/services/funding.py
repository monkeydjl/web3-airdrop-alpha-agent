"""Funding quality scoring (RootData / CryptoRank / manual signals).

Maps raise amount, recency, round count, and investor prestige into:
- funding_tier: tier1 | tier2 | tier3 | unknown | none
- funding_quality: 0.0–1.0 for team / transparency / airdrop bonuses
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

# Prestige investors (substring match, lowercased)
TIER1_INVESTORS = (
    "a16z",
    "andreessen",
    "paradigm",
    "sequoia",
    "polychain",
    "pantera",
    "dragonfly",
    "binance labs",
    "binancelabs",
    "coinbase ventures",
    "coinbase",
    "framework ventures",
    "framework",
    "variant",
    "lightspeed",
    "multicoin",
    "placeholder",
    "electric capital",
    "haun",
    "founders fund",
    "softbank",
    "temasek",
    "tiger global",
    "jump crypto",
    "delphi digital",
    "galaxy",
    "animoca",
    "okx ventures",
    "bybit",
    "hashkey",
    "spartan",
    "mechanism capital",
    "robot ventures",
    "1kx",
    "blockchain capital",
    "usv",
    "union square ventures",
)

TIER2_INVESTORS = (
    "hack vc",
    "hack.vc",
    "delphi ventures",
    "iosg",
    "ngc",
    "fenbushi",
    "hash global",
    "spark digital",
    "dao5",
    "continue capital",
    "gumi cryptos",
    "infinite capital",
    "kr1",
    "outliers",
    "longhash",
    "yzi labs",
    "yzilabs",
    "mirana",
    "spartan group",
    "defiance",
    "cms holdings",
    "cumberland",
    "wintermute",
    "dwf",
)


def _parse_amount(value: Any) -> float | None:
    if value is None or value == "" or value == "--":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().upper().replace(",", "").replace("$", "")
    mult = 1.0
    if s.endswith("B"):
        mult = 1_000_000_000
        s = s[:-1]
    elif s.endswith("M"):
        mult = 1_000_000
        s = s[:-1]
    elif s.endswith("K"):
        mult = 1_000
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def _parse_date(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # ms or s timestamp
        ts = float(value)
        if ts > 1e12:
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=UTC)
        except (OSError, ValueError, OverflowError):
            return None
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%b %d, %Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            dt = datetime.strptime(s[:19].replace("Z", ""), fmt.replace("Z", ""))
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def classify_investor_tier(investors: list[str]) -> str:
    """Return best tier among investor names."""
    blob = " | ".join(i.lower() for i in investors if i)
    if any(t in blob for t in TIER1_INVESTORS):
        return "tier1"
    if any(t in blob for t in TIER2_INVESTORS):
        return "tier2"
    if investors:
        return "tier3"
    return "unknown"


def compute_funding_quality(
    *,
    total_usd: float | None,
    rounds: int,
    last_date: str | None,
    investors: list[str],
    lead_investors: list[str] | None = None,
    recent_funding_flag: bool = False,
) -> dict[str, Any]:
    """Compute funding_tier + funding_quality 0-1."""
    leads = lead_investors or []
    all_inv = list(dict.fromkeys([*leads, *investors]))
    tier = classify_investor_tier(all_inv)

    if not recent_funding_flag and (total_usd is None or total_usd <= 0) and rounds <= 0 and not all_inv:
        return {
            "funding_tier": "none",
            "funding_quality": 0.0,
            "funding_total_usd": total_usd,
            "funding_rounds": rounds,
            "funding_last_date": last_date,
            "funding_investors": all_inv,
            "funding_lead_investors": leads,
            "days_since_round": None,
        }

    score = 0.15  # has some funding signal
    if recent_funding_flag and (total_usd is None or total_usd <= 0) and not all_inv:
        score = 0.35  # boolean-only legacy signal
        tier = tier if tier != "none" else "unknown"

    # Amount
    if total_usd is not None:
        if total_usd >= 50_000_000:
            score += 0.30
        elif total_usd >= 20_000_000:
            score += 0.24
        elif total_usd >= 5_000_000:
            score += 0.18
        elif total_usd >= 1_000_000:
            score += 0.12
        elif total_usd > 0:
            score += 0.06

    # Rounds (maturity of capital formation)
    if rounds >= 4:
        score += 0.12
    elif rounds >= 2:
        score += 0.08
    elif rounds == 1:
        score += 0.04

    # Investor tier
    if tier == "tier1":
        score += 0.28
    elif tier == "tier2":
        score += 0.16
    elif tier == "tier3":
        score += 0.06

    # Recency
    days = None
    dt = _parse_date(last_date)
    if dt is not None:
        days = max(0, (datetime.now(UTC) - dt).days)
        if days <= 90:
            score += 0.15
        elif days <= 180:
            score += 0.10
        elif days <= 365:
            score += 0.05
        elif days > 730:
            score -= 0.05

    quality = max(0.0, min(1.0, score))
    if quality > 0 and tier == "none":
        tier = "unknown"

    return {
        "funding_tier": tier,
        "funding_quality": round(quality, 3),
        "funding_total_usd": total_usd,
        "funding_rounds": rounds,
        "funding_last_date": last_date,
        "funding_investors": all_inv[:30],
        "funding_lead_investors": leads[:15],
        "days_since_round": days,
    }


def extract_funding_from_raw(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize heterogeneous RootData / CryptoRank / manual funding fields."""
    total = (
        _parse_amount(raw.get("funding_total_usd"))
        or _parse_amount(raw.get("total_funding"))
        or _parse_amount(raw.get("raise"))
        or _parse_amount(raw.get("amount"))
        or _parse_amount(raw.get("raised"))
    )
    rounds = raw.get("funding_rounds") or raw.get("rounds") or raw.get("round_count") or 0
    try:
        rounds = int(rounds)
    except (TypeError, ValueError):
        rounds = 0

    # investors may be list of str or list of dict
    inv_raw = raw.get("funding_investors") or raw.get("investors") or raw.get("investor") or []
    investors: list[str] = []
    if isinstance(inv_raw, str):
        investors = [x.strip() for x in inv_raw.split(",") if x.strip()]
    elif isinstance(inv_raw, list):
        for x in inv_raw:
            if isinstance(x, str):
                investors.append(x.strip())
            elif isinstance(x, dict):
                name = x.get("name") or x.get("investor") or x.get("org_name")
                if name:
                    investors.append(str(name).strip())

    leads_raw = raw.get("funding_lead_investors") or raw.get("lead_investors") or raw.get("leads") or []
    leads: list[str] = []
    if isinstance(leads_raw, str):
        leads = [x.strip() for x in leads_raw.split(",") if x.strip()]
    elif isinstance(leads_raw, list):
        for x in leads_raw:
            if isinstance(x, str):
                leads.append(x.strip())
            elif isinstance(x, dict):
                name = x.get("name") or x.get("investor")
                if name:
                    leads.append(str(name).strip())

    # rounds array from RootData get_fac style
    fac = raw.get("fac") or raw.get("fundraising") or raw.get("rounds_detail") or []
    if isinstance(fac, list) and fac:
        rounds = max(rounds, len(fac))
        amounts = []
        dates = []
        for row in fac:
            if not isinstance(row, dict):
                continue
            amounts.append(_parse_amount(row.get("amount") or row.get("raise") or row.get("money")))
            d = row.get("date") or row.get("time") or row.get("published_time")
            if d:
                dates.append(d)
            for key in ("investors", "investor", "leads", "lead_investor"):
                block = row.get(key)
                if isinstance(block, list):
                    for it in block:
                        if isinstance(it, str):
                            investors.append(it)
                        elif isinstance(it, dict) and it.get("name"):
                            investors.append(str(it["name"]))
                elif isinstance(block, str):
                    investors.extend([x.strip() for x in block.split(",") if x.strip()])
        valid_amts = [a for a in amounts if a]
        if valid_amts and total is None:
            total = sum(valid_amts)
        if dates and not raw.get("funding_last_date"):
            # pick latest parseable
            parsed = [(d, _parse_date(d)) for d in dates]
            parsed = [(d, dt) for d, dt in parsed if dt]
            if parsed:
                parsed.sort(key=lambda x: x[1], reverse=True)
                raw = {**raw, "funding_last_date": str(parsed[0][0])[:10]}

    last_date = (
        raw.get("funding_last_date")
        or raw.get("last_funding_date")
        or raw.get("latest_funding_date")
        or raw.get("announce_date")
    )
    if last_date is not None:
        last_date = str(last_date)[:10]

    investors = list(dict.fromkeys([i for i in investors if i]))
    leads = list(dict.fromkeys([i for i in leads if i]))

    recent_flag = bool(raw.get("recent_funding"))
    # auto recent if last round within 365d
    dt = _parse_date(last_date)
    if dt and (datetime.now(UTC) - dt).days <= 365:
        recent_flag = True
    if total and total > 0:
        recent_flag = recent_flag or True  # has amount counts as funding signal

    return compute_funding_quality(
        total_usd=total,
        rounds=rounds,
        last_date=last_date,
        investors=investors,
        lead_investors=leads,
        recent_funding_flag=recent_flag or bool(investors) or rounds > 0,
    )
