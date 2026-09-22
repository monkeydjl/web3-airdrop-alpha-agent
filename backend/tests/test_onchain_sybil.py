"""Unit tests for onchain_sybil service and API endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.onchain_sybil import evaluate_sybil_risk, generate_sybil_routing_topology


def test_generate_sybil_routing_topology() -> None:
    topo = generate_sybil_routing_topology(wallet_count=3, project_name="Berachain")
    assert topo.wallet_count == 3
    assert topo.project_name == "Berachain"
    assert len(topo.nodes) == 9  # 3 cex + 3 wallets + 3 deposit
    assert len(topo.edges) >= 6
    assert "graph TD" in topo.mermaid_diagram
    assert len(topo.critical_rules) >= 4

    data = topo.to_dict()
    assert data["wallet_count"] == 3
    assert len(data["nodes"]) == 9


def test_evaluate_sybil_risk_single_or_empty() -> None:
    res = evaluate_sybil_risk([])
    assert res["is_clean"] is True
    assert res["risk_score"] == 0

    res2 = evaluate_sybil_risk(["0x1111111111111111111111111111111111111111"])
    assert res2["is_clean"] is True
    assert res2["risk_score"] == 0


def test_evaluate_sybil_risk_clean_cluster() -> None:
    addresses = [
        "0x1111111111111111111111111111111111111111",
        "0x2222222222222222222222222222222222222222",
        "0x3333333333333333333333333333333333333333",
    ]
    res = evaluate_sybil_risk(addresses)
    assert res["address_count"] == 3
    assert res["risk_score"] <= 30
    assert res["is_clean"] is True
    assert len(res["findings"]) > 0


def test_evaluate_sybil_risk_similar_prefix() -> None:
    # Addresses with identical vanity prefix (0x8888 followed by 36 hex chars = 42 chars total)
    addresses = [
        "0x8888aa1111111111111111111111111111111111",
        "0x8888aa2222222222222222222222222222222222",
    ]
    res = evaluate_sybil_risk(addresses)
    assert res["risk_score"] >= 50
    assert any("前缀" in f for f in res["findings"])


def test_onchain_sybil_api_endpoints() -> None:
    client = TestClient(app)

    # Test POST /api/v1/onchain/sybil-check
    payload = {
        "addresses": [
            "0x1234567890123456789012345678901234567890",
            "0xabcdefabcdefabcdefabcdefabcdefabcdefabcd",
        ]
    }
    res = client.post("/api/v1/onchain/sybil-check", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["address_count"] == 2

    # Test GET /api/v1/onchain/sybil-topology
    res_topo = client.get("/api/v1/onchain/sybil-topology?wallet_count=4&project_name=Story")
    assert res_topo.status_code == 200
    topo_data = res_topo.json()
    assert topo_data["ok"] is True
    assert topo_data["data"]["wallet_count"] == 4
