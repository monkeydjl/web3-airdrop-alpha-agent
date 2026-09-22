import pytest
from app.services.sell_off_simulator import simulate_sell_off_strategies


def test_simulate_sell_off_strategies_basic():
    res = simulate_sell_off_strategies(
        token_amount=1000.0,
        initial_price_usd=2.0,
        sector="layer2",
        persona="balanced",
    )
    assert res["ok"] is True
    assert res["input_summary"]["initial_gross_value_usd"] == 2000.0
    assert len(res["strategies"]) == 4

    strategy_ids = [s["strategy_id"] for s in res["strategies"]]
    assert "instant_dump" in strategy_ids
    assert "dca_30d" in strategy_ids
    assert "moonbag_50_50" in strategy_ids
    assert "staking_yield" in strategy_ids

    assert res["recommended_strategy"] in strategy_ids
    assert len(res["recommendation_rationale"]) > 0


def test_simulate_sell_off_strategies_personas():
    # Conservative persona should recommend instant_dump
    res_cons = simulate_sell_off_strategies(
        token_amount=500.0,
        initial_price_usd=1.5,
        sector="layer2",
        persona="conservative",
    )
    assert res_cons["recommended_strategy"] == "instant_dump"

    # Aggressive persona on infra
    res_agg = simulate_sell_off_strategies(
        token_amount=1000.0,
        initial_price_usd=5.0,
        sector="infrastructure",
        persona="aggressive",
    )
    assert res_agg["recommended_strategy"] in ["moonbag_50_50", "staking_yield"]
