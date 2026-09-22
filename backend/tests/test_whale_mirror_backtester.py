"""Tests for Whale Mirror Backtester."""

from app.services.whale_mirror_backtester import compare_wallet_with_whale, list_whale_benchmarks


def test_list_whale_benchmarks() -> None:
    benchmarks = list_whale_benchmarks()
    assert len(benchmarks) >= 3
    ids = [b["airdrop_id"] for b in benchmarks]
    assert "arbitrum_top_tier" in ids
    assert "layerzero_top_tier" in ids


def test_compare_wallet_with_whale() -> None:
    res = compare_wallet_with_whale(
        benchmark_id="arbitrum_top_tier",
        user_active_months=8,
        user_total_txs=60,
        user_contracts=30,
        user_bridged_usd=12000.0,
        user_retained_eth=0.06,
        target_project="Monad",
    )
    assert res["match_score"] >= 80.0
    assert res["match_tier"] in ("TOP_WHALE_TIER", "ACTIVE_HUNTER")
    assert len(res["gap_analysis"]) == 5
    assert len(res["action_plan_for_target"]) >= 3
