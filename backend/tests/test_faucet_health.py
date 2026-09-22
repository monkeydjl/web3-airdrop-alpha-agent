"""Unit tests for faucet health check service and endpoints."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.services.faucet_registry import check_faucets_liveness


@pytest.mark.asyncio
@respx.mock
async def test_check_faucets_liveness_all() -> None:
    # Mock HTTP GET calls for faucets without vault address
    respx.get(url__regex=r".*").mock(return_value=httpx.Response(200))

    results = await check_faucets_liveness()
    assert len(results) > 0
    first = results[0]
    assert "id" in first
    assert "health" in first
    assert first["health"] in ("healthy", "low_balance", "depleted", "degraded")
    assert "health_zh" in first
    assert "latency_ms" in first


@pytest.mark.asyncio
@respx.mock
async def test_check_faucets_liveness_single() -> None:
    respx.get("https://sepolia-faucet.pk910.de/").mock(return_value=httpx.Response(200))

    results = await check_faucets_liveness(faucet_id="sepolia-pow")
    assert len(results) == 1
    assert results[0]["id"] == "sepolia-pow"
    assert results[0]["health"] == "healthy"


def test_faucets_health_api_route() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/faucets/health?faucet_id=sepolia-pow")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["total_checked"] == 1
    assert len(data["data"]["statuses"]) == 1
