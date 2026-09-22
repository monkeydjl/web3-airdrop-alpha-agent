"""API tests for Batch 5 Advanced Endpoints:
1. Sybil Lineage Graph (/api/v1/lineage/detect)
2. Calldata Decoder (/api/v1/calldata/decode)
3. Points Epoch Estimator (/api/v1/points/supported-protocols & /api/v1/points/estimate)
4. Daily Evening Alpha Briefing (/api/v1/daily-briefing/today)
"""

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app


def test_batch5_api_endpoints():
    init_db()
    app = create_app()
    client = TestClient(app)

    # 1. Lineage Graph
    resp_lineage = client.post(
        "/api/v1/lineage/detect",
        json={
            "wallet_addresses": [
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
                "0x3333333333333333333333333333333333333333",
            ]
        }
    )
    assert resp_lineage.status_code == 200
    data_lineage = resp_lineage.json()
    assert data_lineage["ok"] is True
    assert "isolation_score" in data_lineage
    assert len(data_lineage["nodes"]) >= 3

    # 2. Calldata Decoder
    resp_calldata = client.post(
        "/api/v1/calldata/decode",
        json={
            "contract_address": "0x6b175474e89094c44da98b954eedeac495271d0f",
            "calldata": "0xa9059cbb00000000000000000000000012345678901234567890123456789012345678900000000000000000000000000000000000000000000000000000000000000064",
            "value_eth": 0.0,
        }
    )
    assert resp_calldata.status_code == 200
    data_calldata = resp_calldata.json()
    assert data_calldata["ok"] is True
    assert data_calldata["function_name"] == "transfer"
    assert data_calldata["safety_rating"] == "safe"

    # 3. Points Estimator
    resp_protos = client.get("/api/v1/points/supported-protocols")
    assert resp_protos.status_code == 200
    assert len(resp_protos.json()["data"]) >= 4

    resp_estimate = client.post(
        "/api/v1/points/estimate",
        json={
            "protocol_id": "scroll_marks",
            "user_points": 30000,
            "capital_invested_usd": 1500,
            "days_active": 40,
        }
    )
    assert resp_estimate.status_code == 200
    data_estimate = resp_estimate.json()
    assert data_estimate["ok"] is True
    assert data_estimate["valuation"]["estimated_tokens"] > 0
    assert data_estimate["valuation"]["tier"] == "pioneer"

    # 4. Daily Briefing
    resp_briefing = client.get("/api/v1/daily-briefing/today")
    assert resp_briefing.status_code == 200
    data_briefing = resp_briefing.json()
    assert data_briefing["ok"] is True
    assert len(data_briefing["top_three_actions"]) == 3
    assert len(data_briefing["markdown_content"]) > 100
