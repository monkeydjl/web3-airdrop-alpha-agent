"""Tests for Impermanent Loss & Liquidation Sentinel."""

from app.services.impermanent_loss_sentinel import (
    calculate_amm_impermanent_loss,
    check_lending_health_factor,
)


def test_calculate_amm_impermanent_loss() -> None:
    res = calculate_amm_impermanent_loss(
        initial_deposit_usd=5000.0,
        price_change_pct=25.0,
        is_concentrated_v3=True,
        fee_apy_pct=30.0,
        holding_days=60,
    )
    assert res["impermanent_loss_pct"] > 0
    assert res["earned_fee_usd"] > 0
    assert "net_pnl_usd" in res
    assert "risk_evaluation" in res


def test_check_lending_health_factor_safe() -> None:
    res = check_lending_health_factor(
        collateral_asset="ETH",
        collateral_amount=10.0,
        collateral_price_usd=3000.0,  # $30,000 collateral
        liquidation_threshold=0.8,
        borrowed_usd=10000.0,  # $10,000 borrow -> HF = (30,000 * 0.8) / 10,000 = 2.4
    )
    assert res["health_factor"] >= 2.0
    assert res["status"] == "SAFE"
    assert res["liquidation_price_usd"] < 2000.0


def test_check_lending_health_factor_danger() -> None:
    res = check_lending_health_factor(
        collateral_asset="ETH",
        collateral_amount=4.0,
        collateral_price_usd=3000.0,  # $12,000 collateral
        liquidation_threshold=0.8,
        borrowed_usd=9000.0,  # HF = (12,000 * 0.8) / 9,000 = 1.066
    )
    assert res["health_factor"] < 1.15
    assert res["status"] in ("HIGH_RISK", "CRITICAL_LIQUIDATION_IMMINENT")
