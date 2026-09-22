import pytest
from app.services.points_epoch_estimator import (
    get_supported_protocols,
    estimate_points_airdrop,
)


def test_get_supported_protocols():
    protocols = get_supported_protocols()
    assert len(protocols) >= 5
    ids = [p["id"] for p in protocols]
    assert "scroll_marks" in ids
    assert "hyperliquid_points" in ids
    assert "symbiotic_points" in ids


def test_estimate_points_airdrop_scroll():
    res = estimate_points_airdrop(
        protocol_id="scroll_marks",
        user_points=50_000,
        capital_invested_usd=1_000,
        days_active=45,
    )
    assert res["ok"] is True
    assert res["valuation"]["share_of_pool_pct"] > 0
    assert res["valuation"]["estimated_tokens"] > 0
    assert res["valuation"]["estimated_usd_value"] > 0
    assert res["valuation"]["tier"] in ["whale", "pioneer", "active", "dust"]
    assert len(res["boost_strategies"]) >= 2
    assert "sprint_advice" in res


def test_estimate_points_airdrop_hyperliquid():
    res = estimate_points_airdrop(
        protocol_id="hyperliquid_points",
        user_points=25_000,
        capital_invested_usd=10_000,
        days_active=60,
    )
    assert res["ok"] is True
    assert res["valuation"]["tier"] == "whale"
    assert res["valuation"]["next_tier_target_points"] is None
