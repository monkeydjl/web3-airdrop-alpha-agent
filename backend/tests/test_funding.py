"""Funding quality unit tests."""

from app.services.funding import (
    classify_investor_tier,
    compute_funding_quality,
    extract_funding_from_raw,
)


def test_tier1_investor():
    assert classify_investor_tier(["a16z crypto", "Random Fund"]) == "tier1"
    assert classify_investor_tier(["Some Angel"]) == "tier3"
    assert classify_investor_tier([]) == "unknown"


def test_compute_quality_large_tier1_recent():
    q = compute_funding_quality(
        total_usd=25_000_000,
        rounds=2,
        last_date="2026-06-01",
        investors=["Paradigm", "Local Ventures"],
        lead_investors=["Paradigm"],
        recent_funding_flag=True,
    )
    assert q["funding_tier"] == "tier1"
    assert q["funding_quality"] >= 0.6


def test_extract_from_rootdata_style():
    raw = {
        "fac": [
            {
                "amount": "5M",
                "date": "2026-05-10",
                "investors": [{"name": "Binance Labs"}, {"name": "HashKey"}],
            },
            {
                "amount": "$2M",
                "date": "2025-01-01",
                "investors": "Seed Fund",
            },
        ]
    }
    q = extract_funding_from_raw(raw)
    assert q["funding_rounds"] >= 2
    assert q["funding_total_usd"] is not None and q["funding_total_usd"] >= 6_000_000
    assert q["funding_tier"] == "tier1"
    assert q["funding_quality"] > 0.4
