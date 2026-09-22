"""Unit tests for Bridge Optimizer Service."""

from app.services.bridge_optimizer import (
    calculate_bridge_routes,
    get_supported_bridge_chains,
)


def test_get_supported_bridge_chains():
    chains = get_supported_bridge_chains()
    assert len(chains) >= 8
    chain_ids = [c["id"] for c in chains]
    assert "arbitrum" in chain_ids
    assert "base" in chain_ids
    assert "ethereum" in chain_ids


def test_calculate_bridge_routes_l2_to_l2():
    res = calculate_bridge_routes(
        source_chain="arbitrum",
        target_chain="base",
        token="ETH",
        amount=0.5,
    )
    assert res["ok"] is True
    assert res["source_chain"] == "arbitrum"
    assert res["target_chain"] == "base"
    assert len(res["routes"]) >= 4
    assert res["cheapest_route"] is not None
    assert res["fastest_route"] is not None
    assert res["estimated_savings_usd"] >= 0
    assert len(res["sybil_safe_tips"]) == 4


def test_calculate_bridge_routes_l1_to_l2():
    res = calculate_bridge_routes(
        source_chain="ethereum",
        target_chain="optimism",
        token="USDC",
        amount=1000.0,
    )
    assert res["ok"] is True
    proto_ids = [r["protocol_id"] for r in res["routes"]]
    assert "across" in proto_ids
    assert "canonical" in proto_ids
