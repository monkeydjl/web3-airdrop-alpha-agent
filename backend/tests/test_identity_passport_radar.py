"""Tests for Web3 Identity & Passport Radar."""

from app.services.identity_passport_radar import evaluate_wallet_identity, get_stamping_guide


def test_get_stamping_guide() -> None:
    guide = get_stamping_guide()
    assert len(guide) >= 8
    # Top ROI stamps should have high weight relative to cost
    first = guide[0]
    assert "weight" in first
    assert "cost_usd" in first


def test_evaluate_wallet_identity() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    res = evaluate_wallet_identity(addr)
    assert res["wallet_address"] == addr
    assert "passport_score" in res
    assert res["passport_score"] >= 0
    assert "is_human_verified" in res
    assert len(res["active_stamps"]) > 0 or len(res["missing_stamps"]) > 0
    assert "recommended_next_stamps" in res
