"""API endpoint integration tests for RBAC middleware (W12-07, ADR-008 §2 & ROADMAP §25.7)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_access_token
from app.config import settings
from app.db import get_connection
from app.main import create_app
from app.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def clean_auth_db():
    """Ensure clean auth tables before each test."""
    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM users")
        conn.commit()


@pytest.fixture
def rbac_client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    with TestClient(create_app()) as client:
        yield client


@pytest.fixture
def tokens(rbac_client: TestClient):
    """Generate tokens for all 4 roles."""
    # 1. Register admin
    res = rbac_client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "Password123", "display_name": "Admin User"},
    )
    assert res.status_code == 200
    admin_token = res.json()["access_token"]

    # 2. Register viewer
    res = rbac_client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@example.com", "password": "Password123", "display_name": "Viewer User"},
    )
    assert res.status_code == 200
    viewer_token = res.json()["access_token"]

    # 3. Create analyst user directly in repo and issue token
    with get_connection() as conn:
        repo = UserRepository(conn)
        analyst_user = repo.create_user(
            user_id="usr_analyst_001",
            email="analyst@example.com",
            password_hash="fakehash",
            role="analyst",
            display_name="Analyst User",
        )
    analyst_token, _, _ = issue_access_token(analyst_user["id"], role="analyst")

    # 4. Anonymous token
    res = rbac_client.post("/api/v1/auth/anonymous")
    assert res.status_code == 200
    anon_token = res.json()["access_token"]

    return {
        "admin": admin_token,
        "analyst": analyst_token,
        "viewer": viewer_token,
        "anonymous": anon_token,
    }


class TestRBACEndpoints:
    """Test RBAC role enforcement across API endpoints."""

    def test_admin_access(self, rbac_client: TestClient, tokens: dict[str, str]) -> None:
        headers = {"Authorization": f"Bearer {tokens['admin']}"}

        # Public & read
        res = rbac_client.get("/api/v1/projects", headers=headers)
        assert res.status_code == 200

        # Admin-only settings
        res = rbac_client.get("/api/v1/settings/config", headers=headers)
        assert res.status_code == 200

        # Admin-only run (passes auth, fails validation on invalid body)
        res = rbac_client.post("/api/v1/run", headers=headers, json={"projects": "invalid"})
        assert res.status_code == 422

        # Re-score (ghost endpoint: passes auth, gets 404 from router)
        res = rbac_client.post("/api/v1/re-score/1", headers=headers)
        assert res.status_code == 404

        # Feedback
        res = rbac_client.post("/api/v1/feedback", headers=headers, json={})
        assert res.status_code == 422  # auth passed

    def test_analyst_access(self, rbac_client: TestClient, tokens: dict[str, str]) -> None:
        headers = {"Authorization": f"Bearer {tokens['analyst']}"}

        # Public & read
        res = rbac_client.get("/api/v1/projects", headers=headers)
        assert res.status_code == 200

        # Feedback is permitted for analyst
        res = rbac_client.post("/api/v1/feedback", headers=headers, json={})
        assert res.status_code == 422  # auth passed

        # Re-score is permitted for analyst (passes auth, returns 404 router)
        res = rbac_client.post("/api/v1/re-score/1", headers=headers)
        assert res.status_code == 404

        # Admin-only run is forbidden (403)
        res = rbac_client.post("/api/v1/run", headers=headers, json={})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Admin-only settings is forbidden (403)
        res = rbac_client.get("/api/v1/settings/config", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Admin-only collections write is forbidden (403)
        res = rbac_client.post("/api/v1/collections/github/trigger", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

    def test_viewer_access(self, rbac_client: TestClient, tokens: dict[str, str]) -> None:
        headers = {"Authorization": f"Bearer {tokens['viewer']}"}

        # Public & read
        res = rbac_client.get("/api/v1/projects", headers=headers)
        assert res.status_code == 200

        # Own auth state is permitted
        res = rbac_client.get("/api/v1/auth/me", headers=headers)
        assert res.status_code == 200
        assert res.json()["role"] == "viewer"

        # Feedback is forbidden for viewer (403, ROADMAP §25.2)
        res = rbac_client.post("/api/v1/feedback", headers=headers, json={})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Batch feedback is forbidden for viewer (403)
        res = rbac_client.post("/api/v1/feedback/batch", headers=headers, json={})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Watchlist modification is forbidden for viewer (403)
        res = rbac_client.post("/api/v1/watchlist/test-proj", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Re-score is forbidden for viewer (403)
        res = rbac_client.post("/api/v1/re-score/1", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Run is forbidden for viewer (403)
        res = rbac_client.post("/api/v1/run", headers=headers, json={})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Settings is forbidden for viewer (403)
        res = rbac_client.get("/api/v1/settings/config", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

    def test_anonymous_access(self, rbac_client: TestClient, tokens: dict[str, str]) -> None:
        headers = {"Authorization": f"Bearer {tokens['anonymous']}"}

        # Public & read
        res = rbac_client.get("/api/v1/projects", headers=headers)
        assert res.status_code == 200

        # Feedback is permitted for anonymous (V2 feedback collection)
        res = rbac_client.post("/api/v1/feedback", headers=headers, json={})
        assert res.status_code == 422  # auth passed

        # Run is forbidden for anonymous (403)
        res = rbac_client.post("/api/v1/run", headers=headers, json={})
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Re-score is forbidden for anonymous (403)
        res = rbac_client.post("/api/v1/re-score/1", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # Settings is forbidden for anonymous (403)
        res = rbac_client.get("/api/v1/settings/config", headers=headers)
        assert res.status_code == 403
        assert res.json()["error"]["code"] == "FORBIDDEN"

        # User profile/me requires registered user (401)
        res = rbac_client.get("/api/v1/auth/me", headers=headers)
        assert res.status_code == 401
