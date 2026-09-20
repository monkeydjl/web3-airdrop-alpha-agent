"""Unit tests for faucet registry and cooldown tracker."""

from __future__ import annotations

import sqlite3

from fastapi.testclient import TestClient

from app.main import app
from app.services.faucet_registry import (
    FREE_FAUCETS,
    list_faucets_with_status,
    record_faucet_claim,
    reset_faucet_claim,
)


def test_faucet_registry_flow() -> None:
    conn = sqlite3.connect(":memory:")

    # Initially all ready
    faucets = list_faucets_with_status(conn, user_id="test-user")
    assert len(faucets) == len(FREE_FAUCETS)
    assert all(f["status"] == "ready" for f in faucets)

    # Claim one faucet
    claimed_id = "sepolia-pow"
    res = record_faucet_claim(conn, user_id="test-user", faucet_id=claimed_id)
    assert res["id"] == claimed_id
    assert res["status"] == "cooling"
    assert res["remaining_seconds"] > 0
    assert "小时" in res["remaining_human"]

    # Verify list shows cooling for that one and ready for others
    faucets2 = list_faucets_with_status(conn, user_id="test-user")
    cooling = [f for f in faucets2 if f["status"] == "cooling"]
    ready = [f for f in faucets2 if f["status"] == "ready"]
    assert len(cooling) == 1
    assert cooling[0]["id"] == claimed_id
    assert len(ready) == len(FREE_FAUCETS) - 1

    # Reset claim
    reset_faucet_claim(conn, user_id="test-user", faucet_id=claimed_id)
    faucets3 = list_faucets_with_status(conn, user_id="test-user")
    assert all(f["status"] == "ready" for f in faucets3)

    conn.close()


def test_faucet_api_endpoints() -> None:
    client = TestClient(app)

    # GET /api/v1/faucets
    res = client.get("/api/v1/faucets")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "faucets" in data["data"]
    assert data["data"]["total"] >= 5

    # Filter by chain
    res_chain = client.get("/api/v1/faucets?chain=sepolia")
    assert res_chain.status_code == 200
    chain_faucets = res_chain.json()["data"]["faucets"]
    assert all(f["chain"] == "sepolia" for f in chain_faucets)

    # POST /api/v1/faucets/{id}/claim
    claim_res = client.post("/api/v1/faucets/sepolia-pow/claim")
    assert claim_res.status_code == 200
    assert claim_res.json()["data"]["status"] == "cooling"

    # DELETE /api/v1/faucets/{id}/claim
    reset_res = client.delete("/api/v1/faucets/sepolia-pow/claim")
    assert reset_res.status_code == 200

    # 404 for invalid faucet
    bad_res = client.post("/api/v1/faucets/non-existent-faucet/claim")
    assert bad_res.status_code == 404
