"""Unit tests for ROI simulator service and endpoints."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.roi_simulator import simulate_portfolio_allocation, simulate_project_roi


def test_simulate_project_roi_not_found() -> None:
    res = simulate_project_roi("non-existent-id")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_simulate_portfolio_allocation() -> None:
    res = simulate_portfolio_allocation(total_budget_usd=300.0, weekly_hours=5.0)
    assert res["ok"] is True
    data = res["data"]
    assert data["total_budget_usd"] == 300.0
    assert data["weekly_hours"] == 5.0
    assert len(data["allocations"]) > 0
    assert data["total_expected_return_usd"] > 0
    assert data["portfolio_roi_multiple"] > 0
    assert "summary_advice" in data


def test_roi_simulation_api_endpoints() -> None:
    client = TestClient(app)

    # Test POST /api/v1/roi/simulate/portfolio
    payload = {
        "total_budget_usd": 400.0,
        "weekly_hours": 6.0,
        "risk_appetite": "balanced",
    }
    res = client.post("/api/v1/roi/simulate/portfolio", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["total_budget_usd"] == 400.0
