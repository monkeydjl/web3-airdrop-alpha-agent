import pytest
from app.services.wallet_activity_diagnostic import diagnose_wallet_health


def test_diagnose_wallet_health_defaults():
    res = diagnose_wallet_health("0x1234567890abcdef1234567890abcdef12345678")
    assert res["ok"] is True
    assert 0 <= res["overall_health_score"] <= 100
    assert res["sybil_risk_level"] in ["low", "moderate", "high", "critical"]
    assert "longevity" in res["dimensions"]
    assert "contract_breadth" in res["dimensions"]
    assert "protocol_diversity" in res["dimensions"]
    assert "gas_commitment" in res["dimensions"]
    assert "multichain_footprint" in res["dimensions"]
    assert len(res["actionable_guide"]) > 0


def test_diagnose_wallet_health_high_grade():
    # A stellar wallet: 12 months, 150 txs, 40 contracts, all 5 categories, 0.12 ETH gas, 5 chains
    res = diagnose_wallet_health(
        wallet_address="0x8888888888888888888888888888888888888888",
        active_months=12,
        tx_count=150,
        unique_contracts=40,
        protocol_types=["dex", "lending", "bridge", "nft", "governance"],
        total_gas_spent_eth=0.12,
        chains_active=["ethereum", "arbitrum", "base", "optimism", "polygon"],
    )
    assert res["overall_health_score"] >= 85
    assert res["sybil_risk_level"] == "low"
    assert len(res["vulnerabilities"]) == 0


def test_diagnose_wallet_health_sybil_bot():
    # A sybil bot: 1 month, 15 txs, 2 contracts, 1 category, 0.001 ETH gas, 1 chain
    res = diagnose_wallet_health(
        wallet_address="0x1111111111111111111111111111111111111111",
        active_months=1,
        tx_count=15,
        unique_contracts=2,
        protocol_types=["dex"],
        total_gas_spent_eth=0.001,
        chains_active=["arbitrum"],
    )
    assert res["overall_health_score"] <= 45
    assert res["sybil_risk_level"] in ["high", "critical"]
    assert len(res["vulnerabilities"]) >= 3
