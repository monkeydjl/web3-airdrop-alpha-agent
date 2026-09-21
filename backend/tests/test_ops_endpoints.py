"""Unit tests for ops maintenance endpoints: /ops/sync-funding and /ops/audit-viability."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def auth_setup(tmp_path, monkeypatch):
    test_key = "test-ops-admin-key"
    token_secret = "test-ops-token-secret"
    monkeypatch.setattr(settings, "api_key", test_key)
    monkeypatch.setattr(settings, "auth_token_secret", token_secret)
    monkeypatch.setattr(settings, "app_env", "testing")
    return test_key


@pytest.fixture
def client(auth_setup):
    app = create_app()
    return TestClient(app)


def test_ops_sync_funding_admin_success(client, auth_setup):
    mock_result = {
        "ok": True,
        "total_scanned": 10,
        "matched_protocols": 5,
        "enriched_funding_count": 2,
        "viability_upgraded_count": 1,
        "details": [],
        "applied": False,
    }
    with patch("app.routers.v1.ops.sync_database_defillama_raises", new_callable=AsyncMock) as mock_sync:
        mock_sync.return_value = mock_result
        resp = client.post(
            "/api/v1/ops/sync-funding",
            json={"apply_changes": False, "limit": 10},
            headers={"X-API-Key": auth_setup},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total_scanned"] == 10
        assert data["data"]["enriched_funding_count"] == 2
        mock_sync.assert_awaited_once_with(apply_changes=False, limit=10)


def test_ops_audit_viability_admin_success(client, auth_setup):
    mock_result = {
        "ok": True,
        "total_scanned": 50,
        "tier_counts": {"viable": 10, "borderline": 35, "unviable": 5},
        "reason_counts": {},
        "downgraded_count": 1,
        "downgraded_projects": [],
        "applied": False,
    }
    with patch("app.routers.v1.ops.audit_database_viability") as mock_audit:
        mock_audit.return_value = mock_result
        resp = client.post(
            "/api/v1/ops/audit-viability",
            json={"apply_changes": False},
            headers={"X-API-Key": auth_setup},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["ok"] is True
        assert data["data"]["total_scanned"] == 50
        assert data["data"]["downgraded_count"] == 1
        mock_audit.assert_called_once_with(apply_changes=False)


def test_ops_endpoints_forbidden_for_anonymous(client):
    # Issue anonymous token
    token_resp = client.post("/api/v1/auth/anonymous")
    assert token_resp.status_code == 200
    token = token_resp.json()["access_token"]

    resp = client.post(
        "/api/v1/ops/sync-funding",
        json={"apply_changes": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, f"Expected 403 Forbidden for anonymous, got {resp.status_code}"

    resp = client.post(
        "/api/v1/ops/audit-viability",
        json={"apply_changes": False},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, f"Expected 403 Forbidden for anonymous, got {resp.status_code}"
