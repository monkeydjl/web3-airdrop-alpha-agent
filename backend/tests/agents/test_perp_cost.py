"""Perp DEX high/low cost distinction (RED)."""

from app.agents.base import RawProject
from app.agents.risk import classify_perp_cost_tier, is_perp_dex


def _proj(**updates):
    values = {
        "id": "perp-1",
        "name": "PerpX",
        "sector": "perp-dex",
        "stage": "mainnet",
        "source": "seed",
    }
    values.update(updates)
    return RawProject(**values)


def test_mainnet_perp_with_live_trading_is_high_cost():
    p = _proj(
        stage="mainnet",
        has_points_program=True,
        has_contract=True,
        description="perpetual futures with leverage trading and funding fees",
    )
    assert is_perp_dex(p) is True
    assert classify_perp_cost_tier(p) == "high"


def test_testnet_perp_is_low_cost():
    p = _proj(
        stage="testnet",
        has_testnet=True,
        has_points_program=True,
        description="perpetual DEX testnet, no real funds required",
    )
    assert is_perp_dex(p) is True
    assert classify_perp_cost_tier(p) == "low"


def test_non_perp_returns_none():
    p = _proj(sector="L2", stage="mainnet", description="rollup network")
    assert is_perp_dex(p) is False
    assert classify_perp_cost_tier(p) is None
