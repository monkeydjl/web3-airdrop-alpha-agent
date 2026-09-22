"""API tests for Batch 7 Advanced Endpoints:
1. Identity Passport (/api/v1/identity/evaluate & /stamping-guide)
2. Whale Mirror Backtester (/api/v1/whale-mirror/benchmarks & /compare)
3. Impermanent Loss & Liquidation Sentinel (/api/v1/il-sentinel/calculate-il & /check-lending-health)
4. Gasless Paymaster Sponsor (/api/v1/paymaster/active-sponsorships & /simulate-gasless-tx)
"""

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app


def test_batch7_api_endpoints():
    init_db()
    app = create_app()
    client = TestClient(app)

    # 1. Identity Passport
    resp_guide = client.get("/api/v1/identity/stamping-guide")
    assert resp_guide.status_code == 200
    assert resp_guide.json()["ok"] is True
    assert resp_guide.json()["data"]["total"] >= 8

    resp_eval = client.post(
        "/api/v1/identity/evaluate",
        json={"wallet_address": "0x5555555555555555555555555555555555555555"}
    )
    assert resp_eval.status_code == 200
    assert resp_eval.json()["ok"] is True
    assert "passport_score" in resp_eval.json()["data"]

    # 2. Whale Mirror
    resp_bm = client.get("/api/v1/whale-mirror/benchmarks")
    assert resp_bm.status_code == 200
    assert resp_bm.json()["ok"] is True
    assert resp_bm.json()["data"]["total"] >= 3

    resp_comp = client.post(
        "/api/v1/whale-mirror/compare",
        json={
            "benchmark_id": "arbitrum_top_tier",
            "user_active_months": 5,
            "user_total_txs": 30,
            "user_contracts": 15,
            "user_bridged_usd": 4500.0,
            "user_retained_eth": 0.03,
            "target_project": "Story Protocol",
        }
    )
    assert resp_comp.status_code == 200
    assert resp_comp.json()["ok"] is True
    assert "match_score" in resp_comp.json()["data"]

    # 3. Impermanent Loss & Liquidation
    resp_il = client.post(
        "/api/v1/il-sentinel/calculate-il",
        json={
            "initial_deposit_usd": 10000.0,
            "price_change_pct": 40.0,
            "is_concentrated_v3": True,
            "fee_apy_pct": 35.0,
            "holding_days": 30,
        }
    )
    assert resp_il.status_code == 200
    assert resp_il.json()["ok"] is True
    assert "impermanent_loss_usd" in resp_il.json()["data"]

    resp_lend = client.post(
        "/api/v1/il-sentinel/check-lending-health",
        json={
            "collateral_asset": "ETH",
            "collateral_amount": 6.0,
            "collateral_price_usd": 3200.0,
            "liquidation_threshold": 0.825,
            "borrowed_usd": 8000.0,
        }
    )
    assert resp_lend.status_code == 200
    assert resp_lend.json()["ok"] is True
    assert resp_lend.json()["data"]["health_factor"] >= 1.5

    # 4. Gasless Paymaster
    resp_pm_list = client.get("/api/v1/paymaster/active-sponsorships")
    assert resp_pm_list.status_code == 200
    assert resp_pm_list.json()["ok"] is True
    assert resp_pm_list.json()["data"]["total"] >= 3

    resp_pm_sim = client.post(
        "/api/v1/paymaster/simulate-gasless-tx",
        json={
            "campaign_id": "base_daily_checkin",
            "user_address": "0x7777777777777777777777777777777777777777",
        }
    )
    assert resp_pm_sim.status_code == 200
    assert resp_pm_sim.json()["ok"] is True
    assert resp_pm_sim.json()["data"]["is_sponsored"] is True
