"""Tests for Bridge Liquidity & Peg Radar."""

from app.services.bridge_liquidity_radar import get_bridge_liquidity_overview, simulate_bridge_route


def test_bridge_liquidity_overview() -> None:
    overview = get_bridge_liquidity_overview()
    assert "summary" in overview
    assert overview["summary"]["total_pools_monitored"] >= 4
    assert len(overview["bridge_pools"]) >= 4
    assert len(overview["pegged_assets"]) >= 4

    # Verify LRT / stablecoin tracking
    symbols = [a["symbol"] for a in overview["pegged_assets"]]
    assert "stETH" in symbols
    assert "ezETH" in symbols
    assert "USDe" in symbols


def test_simulate_bridge_route_small_amount() -> None:
    res = simulate_bridge_route(
        from_chain="Ethereum",
        to_chain="Arbitrum",
        asset="USDC",
        amount_usd=1500.0,
    )
    assert res["risk_tier"] == "SAFE"
    assert res["estimated_slippage_pct"] < 0.1
    assert res["net_received_usd"] > 1495.0


def test_simulate_bridge_route_large_amount() -> None:
    res = simulate_bridge_route(
        from_chain="Ethereum",
        to_chain="Arbitrum",
        asset="USDC",
        amount_usd=100000.0,
    )
    assert res["risk_tier"] == "HIGH_SLIPPAGE"
    assert res["estimated_slippage_pct"] >= 1.0
    assert "建议分多批次" in res["guidance"]
