"""API integration tests for HA & Leader Election endpoints (W12-03, ADR-005)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app
from app.services.leader_election import LeaderElector


@pytest.fixture(autouse=True)
def clean_ha_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "ha_api_test.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    init_db()

    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.commit()

    yield

    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.commit()


def test_ha_status_endpoint_default(monkeypatch):
    """GET /api/v1/ha/status returns valid status when HA is disabled (default)."""
    monkeypatch.setattr(settings, "ha_enabled", False)
    app = create_app()

    with TestClient(app) as client:
        res = client.get("/api/v1/ha/status")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ha_enabled"] is False
        assert data["resource_id"] == "unified_scheduler"
        assert "instance_id" in data


def test_ha_status_endpoint_with_active_leader(monkeypatch):
    """GET /api/v1/ha/status correctly reflects leader instance when HA is enabled."""
    monkeypatch.setattr(settings, "ha_enabled", True)
    monkeypatch.setattr(settings, "ha_instance_id", "inst_primary")
    monkeypatch.setattr(settings, "ha_lease_ttl_seconds", 30)

    app = create_app()

    with TestClient(app) as client:
        res = client.get("/api/v1/ha/status")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["ha_enabled"] is True
        assert data["instance_id"] == "inst_primary"
        assert data["is_leader"] is True
        assert data["current_leader"] == "inst_primary"
        assert data["lease_expires_at"] is not None


def test_multi_instance_failover_api(monkeypatch):
    """Verify that secondary instance detects primary step down and takes over."""
    # 1. Primary instance starts and acquires leadership
    elector_primary = LeaderElector(
        get_connection,
        instance_id="inst_primary",
        lease_ttl_seconds=30,
        enabled=True,
    )
    assert elector_primary.acquire_or_renew() is True

    # 2. Secondary app starts as follower
    monkeypatch.setattr(settings, "ha_enabled", True)
    monkeypatch.setattr(settings, "ha_instance_id", "inst_secondary")
    monkeypatch.setattr(settings, "ha_lease_ttl_seconds", 30)

    app_secondary = create_app()
    with TestClient(app_secondary) as client_secondary:
        res = client_secondary.get("/api/v1/ha/status")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["instance_id"] == "inst_secondary"
        assert data["is_leader"] is False
        assert data["current_leader"] == "inst_primary"

        # 3. Primary steps down
        elector_primary._is_leader = True
        assert elector_primary.step_down() is True

        # 4. Secondary attempts to acquire
        secondary_elector = app_secondary.state.leader_elector
        assert secondary_elector.acquire_or_renew() is True
        secondary_elector._is_leader = True

        # 5. Status endpoint on secondary now reflects leadership
        res_after = client_secondary.get("/api/v1/ha/status")
        assert res_after.status_code == 200
        data_after = res_after.json()["data"]
        assert data_after["instance_id"] == "inst_secondary"
        assert data_after["is_leader"] is True
        assert data_after["current_leader"] == "inst_secondary"
