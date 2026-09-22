"""API tests for Batch 4 Advanced Endpoints:
1. Token Unlock Radar (/api/v1/unlocks/schedule & /api/v1/unlocks/project/{id})
2. Gas Alerts & Rules Engine (/api/v1/gas/alerts/rules & /api/v1/gas/alerts/active)
3. Sell-Off Simulator (/api/v1/sell-off/simulate)
4. Wallet Activity Diagnostic (/api/v1/diagnostic/wallet)
"""

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app


def test_batch4_api_endpoints():
    init_db()
    app = create_app()
    client = TestClient(app)

    # 1. Token Unlock Schedule
    resp_unlocks = client.get("/api/v1/unlocks/schedule?limit=5")
    assert resp_unlocks.status_code == 200
    data_unlocks = resp_unlocks.json()
    assert data_unlocks["ok"] is True
    assert len(data_unlocks["data"]) > 0

    # Token Unlock Single Project
    resp_celestia = client.get("/api/v1/unlocks/project/celestia")
    assert resp_celestia.status_code == 200
    assert resp_celestia.json()["data"]["token_symbol"] == "TIA"

    resp_unknown_proj = client.get("/api/v1/unlocks/project/unknown-fake-id-999")
    assert resp_unknown_proj.status_code == 404

    # 2. Gas Alerts & Rules
    resp_rules = client.get("/api/v1/gas/alerts/rules")
    assert resp_rules.status_code == 200
    data_rules = resp_rules.json()
    assert data_rules["ok"] is True
    assert data_rules["count"] >= 4

    resp_add_rule = client.post(
        "/api/v1/gas/alerts/rules",
        json={
            "chain": "polygon",
            "condition": "below",
            "threshold_gwei": 30.0,
            "label": "Polygon Quick Mint",
            "enabled": True,
        }
    )
    assert resp_add_rule.status_code == 200
    created_rule = resp_add_rule.json()["data"]
    rule_id = created_rule["id"]

    resp_active_alerts = client.get("/api/v1/gas/alerts/active")
    assert resp_active_alerts.status_code == 200
    assert "data" in resp_active_alerts.json()

    resp_del_rule = client.delete(f"/api/v1/gas/alerts/rules/{rule_id}")
    assert resp_del_rule.status_code == 200

    # 3. Sell-Off Simulator
    resp_simulate = client.post(
        "/api/v1/sell-off/simulate",
        json={
            "token_amount": 2500.0,
            "initial_price_usd": 3.2,
            "sector": "infrastructure",
            "persona": "balanced",
        }
    )
    assert resp_simulate.status_code == 200
    sim_data = resp_simulate.json()
    assert sim_data["ok"] is True
    assert len(sim_data["strategies"]) == 4
    assert sim_data["recommended_strategy"] in ["moonbag_50_50", "staking_yield", "dca_30d", "instant_dump"]

    # 4. Wallet Activity Diagnostic
    resp_diag = client.post(
        "/api/v1/diagnostic/wallet",
        json={
            "wallet_address": "0x9999999999999999999999999999999999999999",
            "active_months": 8,
            "tx_count": 88,
            "unique_contracts": 28,
            "protocol_types": ["dex", "bridge", "lending"],
            "total_gas_spent_eth": 0.045,
            "chains_active": ["ethereum", "arbitrum", "base"],
        }
    )
    assert resp_diag.status_code == 200
    diag_data = resp_diag.json()
    assert diag_data["ok"] is True
    assert 0 <= diag_data["overall_health_score"] <= 100
    assert "dimensions" in diag_data
    assert len(diag_data["actionable_guide"]) > 0
