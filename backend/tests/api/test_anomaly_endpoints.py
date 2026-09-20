"""API integration tests for Anomaly Detection endpoints (W12-04)."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


def test_get_anomalies_success(client):
    resp = client.get("/api/v1/anomalies")
    assert resp.status_code == 200
    res = resp.json()
    assert res["ok"] is True
    data = res["data"]
    assert "overall_status" in data
    assert data["overall_status"] in ("healthy", "warning", "critical")
    assert "drift_summary" in data
    assert "quality_summary" in data
    assert "anomalies" in data
    assert isinstance(data["anomalies"], list)


def test_get_anomalies_force_refresh(client):
    resp1 = client.get("/api/v1/anomalies?force_refresh=true")
    assert resp1.status_code == 200
    res1 = resp1.json()
    assert res1["ok"] is True

    resp2 = client.get("/api/v1/anomalies?force_refresh=false")
    assert resp2.status_code == 200
    res2 = resp2.json()
    assert res2["ok"] is True
    # Cached checked_at should match
    assert res2["data"]["checked_at"] == res1["data"]["checked_at"]
