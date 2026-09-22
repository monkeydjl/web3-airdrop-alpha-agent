"""Tests for Paymaster Sponsor Radar."""

from app.services.paymaster_sponsor_radar import (
    list_active_paymaster_sponsorships,
    simulate_gasless_tx,
)


def test_list_active_paymaster_sponsorships() -> None:
    sponsorships = list_active_paymaster_sponsorships()
    assert len(sponsorships) >= 3
    chains = [s["chain"] for s in sponsorships]
    assert "Base" in chains
    assert "ZKsync Era" in chains


def test_simulate_gasless_tx() -> None:
    valid_addr = "0x8888888888888888888888888888888888888888"
    res = simulate_gasless_tx(campaign_id="base_daily_checkin", user_address=valid_addr)
    assert res["is_sponsored"] is True
    assert res["gas_cost_user_wei"] == 0
    assert res["gas_saved_usd"] > 0
    assert "符合赞助条件" in res["verdict_notes"]
