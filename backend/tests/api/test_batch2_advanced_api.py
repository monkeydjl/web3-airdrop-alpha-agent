"""API tests for Batch 2 Advanced Endpoints:
1. Security Sentinel (/api/v1/security)
2. Airdrop PnL Ledger (/api/v1/pnl)
3. Script Forge (/api/v1/scripts)
4. Smart Money Radar (/api/v1/smart-money)
"""

from fastapi.testclient import TestClient
from app.main import create_app


def test_batch2_api_endpoints():
    app = create_app()
    client = TestClient(app)

    # 1. Security Sentinel
    res_sec_approvals = client.post(
        "/api/v1/security/approvals",
        json={"wallet_address": "0x1111111254fb6c44bac0bed2854e76f90643097d"},
    )
    assert res_sec_approvals.status_code == 200
    sec_data = res_sec_approvals.json()
    assert sec_data["ok"] is True
    assert "approvals" in sec_data["data"]

    res_sec_domain = client.post(
        "/api/v1/security/domain-check",
        json={"url": "https://story.foundation"},
    )
    assert res_sec_domain.status_code == 200
    domain_data = res_sec_domain.json()
    assert domain_data["ok"] is True
    assert "risk_level" in domain_data["data"]

    # 2. Airdrop PnL
    res_pnl_summary = client.get("/api/v1/pnl/summary")
    assert res_pnl_summary.status_code == 200
    pnl_data = res_pnl_summary.json()
    assert pnl_data["ok"] is True
    assert "records" in pnl_data

    res_pnl_record = client.post(
        "/api/v1/pnl/records",
        json={
            "project_name": "Test Project",
            "token_symbol": "$TST",
            "amount_claimed": 500.0,
            "current_price_usd": 2.5,
            "ath_price_usd": 3.0,
            "gas_spent_usd": 15.0,
            "notes": "E2E Test Note",
        },
    )
    assert res_pnl_record.status_code == 200
    assert res_pnl_record.json()["ok"] is True

    # 3. Script Forge
    res_scripts = client.post(
        "/api/v1/scripts/generate",
        json={
            "project_name": "Test Net",
            "contract_address": "0x1234567890abcdef1234567890abcdef12345678",
            "rpc_url": "https://test.rpc",
            "jitter_range_seconds": [10, 30],
        },
    )
    assert res_scripts.status_code == 200
    scripts_data = res_scripts.json()
    assert scripts_data["ok"] is True
    assert "web3_py" in scripts_data["scripts"]
    assert "foundry_cast" in scripts_data["scripts"]
    assert "viem_ts" in scripts_data["scripts"]

    # 4. Smart Money Radar
    res_sm = client.get("/api/v1/smart-money/feed")
    assert res_sm.status_code == 200
    sm_data = res_sm.json()
    assert sm_data["ok"] is True
    assert len(sm_data["smart_money_activities"]) > 0
    assert "social_velocity_spikes" in sm_data
