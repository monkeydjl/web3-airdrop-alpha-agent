"""Unit tests for Airdrop PnL Service and API."""

from app.services.airdrop_pnl import add_harvest_record, get_pnl_summary


def test_get_pnl_summary():
    """验证收益汇总包含净利润、RoI倍数与猎人段位."""
    summary = get_pnl_summary()
    assert summary["ok"] is True
    assert summary["total_claimed_projects"] >= 4
    assert summary["total_current_value_usd"] > 0
    assert summary["total_ath_value_usd"] > summary["total_current_value_usd"]
    assert "hunter_tier" in summary
    assert "hunter_tier_badge" in summary


def test_add_harvest_record():
    """验证录入新空投记录并能被立刻纳入汇总."""
    new_rec = {
        "project_name": "Test Protocol",
        "token_symbol": "$TEST",
        "amount_claimed": 1000.0,
        "current_price_usd": 1.5,
        "ath_price_usd": 3.0,
        "gas_spent_usd": 12.0,
        "notes": "单元测试记账",
    }
    res = add_harvest_record(new_rec)
    assert res["ok"] is True
    assert res["data"]["token_symbol"] == "$TEST"

    summary = get_pnl_summary()
    matched = [r for r in summary["records"] if r["token_symbol"] == "$TEST"]
    assert len(matched) > 0
    assert matched[0]["net_profit_usd"] == 1500.0 - 12.0
