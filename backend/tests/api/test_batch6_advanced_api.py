"""API tests for Batch 6 Advanced Endpoints:
1. MEV Protection & Private RPC (/api/v1/mev-rpc/nodes & /api/v1/mev-rpc/benchmark)
2. Bridge Liquidity & Depeg Radar (/api/v1/bridge-liquidity/overview & /api/v1/bridge-liquidity/simulate-route)
3. Action Playbook Studio (/api/v1/playbook/templates & /api/v1/playbook/validate-and-generate)
4. Multi-Operator Studio (/api/v1/team-studio/dashboard, /assign-task, /operator)
"""

from fastapi.testclient import TestClient
from app.db import init_db
from app.main import create_app


def test_batch6_api_endpoints():
    init_db()
    app = create_app()
    client = TestClient(app)

    # 1. MEV RPC
    resp_nodes = client.get("/api/v1/mev-rpc/nodes")
    assert resp_nodes.status_code == 200
    data_nodes = resp_nodes.json()
    assert data_nodes["ok"] is True
    assert data_nodes["data"]["total"] >= 4

    resp_bench = client.post(
        "/api/v1/mev-rpc/benchmark",
        json={"node_id": "flashbots_protect"}
    )
    assert resp_bench.status_code == 200
    data_bench = resp_bench.json()
    assert data_bench["ok"] is True
    assert data_bench["data"]["safety_rating"] in ("A+", "A")

    # 2. Bridge Liquidity & Depeg Radar
    resp_bridge_ov = client.get("/api/v1/bridge-liquidity/overview")
    assert resp_bridge_ov.status_code == 200
    data_ov = resp_bridge_ov.json()
    assert data_ov["ok"] is True
    assert data_ov["data"]["summary"]["total_pools_monitored"] >= 4

    resp_bridge_sim = client.post(
        "/api/v1/bridge-liquidity/simulate-route",
        json={
            "from_chain": "Ethereum",
            "to_chain": "Arbitrum",
            "asset": "USDC",
            "amount_usd": 5000.0,
        }
    )
    assert resp_bridge_sim.status_code == 200
    data_sim = resp_bridge_sim.json()
    assert data_sim["ok"] is True
    assert data_sim["data"]["risk_tier"] == "SAFE"

    # 3. Action Playbook Studio
    resp_pb_tpl = client.get("/api/v1/playbook/templates")
    assert resp_pb_tpl.status_code == 200
    data_tpl = resp_pb_tpl.json()
    assert data_tpl["ok"] is True
    assert data_tpl["data"]["total"] >= 3

    resp_pb_gen = client.post(
        "/api/v1/playbook/validate-and-generate",
        json={
            "playbook_id": "playbook_scroll_marks",
            "jitter_min": 30,
            "jitter_max": 60,
        }
    )
    assert resp_pb_gen.status_code == 200
    data_gen = resp_pb_gen.json()
    assert data_gen["ok"] is True
    assert data_gen["data"]["step_count"] == 4
    assert len(data_gen["data"]["executable_code"]) > 100

    # 4. Team Studio
    resp_studio = client.get("/api/v1/team-studio/dashboard")
    assert resp_studio.status_code == 200
    data_studio = resp_studio.json()
    assert data_studio["ok"] is True
    assert data_studio["data"]["summary"]["active_operators_count"] >= 3

    resp_task = client.post(
        "/api/v1/team-studio/assign-task",
        json={
            "title": "Hyperliquid Funding Rate Hedge",
            "project": "Hyperliquid",
            "operator_id": "op_alice",
            "target_wallet_count": 15,
            "priority": "high",
        }
    )
    assert resp_task.status_code == 200
    data_task = resp_task.json()
    assert data_task["ok"] is True
    assert data_task["data"]["success"] is True

    resp_op = client.post(
        "/api/v1/team-studio/operator",
        json={
            "operator_id": "op_eva",
            "name": "Eva (Security Auditor)",
            "role": "Compliance Officer",
            "assigned_wallets": 5,
            "assigned_projects": ["Scroll", "Linea"],
        }
    )
    assert resp_op.status_code == 200
    data_op = resp_op.json()
    assert data_op["ok"] is True
    assert data_op["data"]["action"] == "created"
