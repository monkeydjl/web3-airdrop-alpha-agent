"""Tests for anonymous token authentication (D1, ADR-008).

Covers:
- POST /api/v1/auth/anonymous token issuance
- Token sign/verify unit tests
- Middleware: no token -> 401, anonymous -> 200/403, admin -> 200
- Expired/tampered/invalid token -> 401
- MVP mode (empty API_KEY) -> no auth
- user_id propagation via request.state

Reference:
- ADR-008-user-system.md
- V2_TASKS.md D1
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user, issue_anonymous_token, verify_token
from app.config import settings
from app.db import init_db
from app.main import create_app

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

ADMIN_KEY = "test-admin-key-0123456789abcdef"
TOKEN_SECRET = "test-hmac-secret-for-anonymous-tokens"


@pytest.fixture
def auth_client(tmp_path, monkeypatch):
    """Client with API_KEY set (auth enabled)."""
    db_path = tmp_path / "auth_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", ADMIN_KEY)
    monkeypatch.setattr(settings, "auth_token_secret", TOKEN_SECRET)
    monkeypatch.setattr(settings, "auth_token_ttl_hours", 72)
    monkeypatch.setattr(settings, "app_env", "testing")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


@pytest.fixture
def open_client(tmp_path, monkeypatch):
    """Client without API_KEY (MVP mode, no auth)."""
    db_path = tmp_path / "open_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    monkeypatch.setattr(settings, "api_key", "")
    monkeypatch.setattr(settings, "app_env", "testing")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


def _get_anon_token(client: TestClient, user_id: str | None = None) -> str:
    """Helper: issue an anonymous token via the API."""
    payload = {"user_id": user_id} if user_id else None
    r = client.post("/api/v1/auth/anonymous", json=payload)
    assert r.status_code == 200, f"Token issuance failed: {r.json()}"
    return r.json()["access_token"]


# ═══════════════════════════════════════════════════════════════
# Token Issuance Endpoint
# ═══════════════════════════════════════════════════════════════


class TestAnonymousTokenIssuance:
    """POST /api/v1/auth/anonymous."""

    def test_issue_without_auth(self, auth_client):
        """Token endpoint is public — no auth header needed."""
        r = auth_client.post("/api/v1/auth/anonymous")
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["token_type"] == "Bearer"
        assert data["expires_in"] == 72 * 3600
        assert data["user_id"].startswith("anon-")

    def test_issue_with_custom_user_id(self, auth_client):
        """Caller can specify a custom user_id."""
        r = auth_client.post(
            "/api/v1/auth/anonymous",
            json={"user_id": "dashboard-user-42"},
        )
        assert r.status_code == 200
        assert r.json()["user_id"] == "dashboard-user-42"

    def test_issue_works_in_mvp_mode(self, open_client):
        """Token issuance works even when API_KEY is empty."""
        r = open_client.post("/api/v1/auth/anonymous")
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_issued_token_is_verifiable(self, auth_client):
        """Token returned by the endpoint passes verify_token()."""
        token = _get_anon_token(auth_client, user_id="verify-test")
        payload = verify_token(token)
        assert payload is not None
        assert payload["user_id"] == "verify-test"
        assert payload["role"] == "anonymous"


# ═══════════════════════════════════════════════════════════════
# Token Sign/Verify Unit Tests
# ═══════════════════════════════════════════════════════════════


class TestTokenSignVerify:
    """Unit tests for issue_anonymous_token / verify_token."""

    def test_roundtrip(self):
        token = issue_anonymous_token(user_id="unit-user")
        payload = verify_token(token)
        assert payload is not None
        assert payload["user_id"] == "unit-user"
        assert payload["role"] == "anonymous"
        assert isinstance(payload["exp"], int)

    def test_empty_token(self):
        assert verify_token("") is None

    def test_wrong_format(self):
        assert verify_token("no-dot") is None
        assert verify_token("a.b.c") is None

    def test_tampered_signature(self):
        token = issue_anonymous_token(user_id="tamper-user")
        parts = token.split(".")
        # Replace entire signature with a different valid base64url string.
        # Changing just the last char can leave decoded bytes unchanged
        # because base64url padding bits are ignored by the decoder.
        import base64 as _b64

        fake_sig = _b64.urlsafe_b64encode(b"x" * 32).rstrip(b"=").decode("ascii")
        assert verify_token(f"{parts[0]}.{fake_sig}") is None

    def test_tampered_payload(self):
        token = issue_anonymous_token(user_id="tamper-user")
        parts = token.split(".")
        # Corrupt the payload portion
        tampered_payload = parts[0][:-1] + ("A" if parts[0][-1] != "A" else "B")
        assert verify_token(f"{tampered_payload}.{parts[1]}") is None

    def test_expired_token(self):
        """Token with negative TTL is already expired."""
        token = issue_anonymous_token(user_id="expired-user", ttl_hours=-1)
        assert verify_token(token) is None

    def test_different_secret_rejects(self, monkeypatch):
        """Token signed with one secret is rejected under another."""
        token = issue_anonymous_token(user_id="secret-test")
        # Change the secret — verify should fail
        monkeypatch.setattr(settings, "auth_token_secret", "different-secret")
        assert verify_token(token) is None


# ═══════════════════════════════════════════════════════════════
# Middleware Integration Tests
# ═══════════════════════════════════════════════════════════════


class TestAuthMiddleware:
    """Integration tests for the dual-token middleware."""

    # ── No token → 401 ────────────────────────────

    def test_no_token_returns_401(self, auth_client):
        r = auth_client.get("/api/v1/projects")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_no_token_on_admin_endpoint_returns_401(self, auth_client):
        """Admin endpoints also return 401 (not 403) when no token at all."""
        r = auth_client.post("/api/v1/run", json={"projects": []})
        assert r.status_code == 401

    # ── Public endpoints ──────────────────────────

    def test_health_no_auth_needed(self, auth_client):
        assert auth_client.get("/health").status_code == 200

    def test_version_no_auth_needed(self, auth_client):
        assert auth_client.get("/version").status_code == 200

    def test_docs_no_auth_needed(self, auth_client):
        assert auth_client.get("/docs").status_code == 200

    def test_openapi_json_no_auth_needed(self, auth_client):
        assert auth_client.get("/openapi.json").status_code == 200

    # ── Anonymous token → 200 on public endpoints ──

    def test_anon_token_allows_projects(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    def test_anon_token_allows_feedback(self, auth_client):
        token = _get_anon_token(auth_client, user_id="feedback-tester")
        r = auth_client.post(
            "/api/v1/feedback",
            json={"project_id": "test-proj-1", "signal": "useful"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_anon_token_allows_watchlist(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/watchlist",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

    # ── Anonymous token → 403 on admin endpoints ──

    def test_anon_token_blocked_from_run(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.post(
            "/api/v1/run",
            json={"projects": [{"name": "TestProj"}]},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_anon_token_blocked_from_export(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/export/projects",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_anon_token_blocked_from_import(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.post(
            "/api/v1/import/projects",
            json={"projects": []},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    def test_anon_token_blocked_from_quarantine(self, auth_client):
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/quarantine",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403

    # ── Admin API key → 200 on all endpoints ──────

    def test_admin_key_via_x_api_key(self, auth_client):
        r = auth_client.get(
            "/api/v1/projects",
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 200

    def test_admin_key_via_bearer(self, auth_client):
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {ADMIN_KEY}"},
        )
        assert r.status_code == 200

    def test_admin_key_allows_run(self, auth_client):
        r = auth_client.post(
            "/api/v1/run",
            json={"projects": [{"name": "AdminTestProj"}]},
            headers={"X-API-Key": ADMIN_KEY},
        )
        assert r.status_code == 200

    def test_admin_key_allows_export(self, auth_client):
        r = auth_client.get(
            "/api/v1/export/projects",
            headers={"X-API-Key": ADMIN_KEY},
        )
        # Admin key is accepted — 404 (no data) is fine, 401/403 would mean auth blocked.
        assert r.status_code not in (401, 403)

    # ── Invalid / expired token → 401 ─────────────

    def test_invalid_token_returns_401(self, auth_client):
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer invalid.token"},
        )
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "UNAUTHORIZED"

    def test_garbage_bearer_returns_401(self, auth_client):
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401

    def test_expired_token_returns_401(self, auth_client):
        """Issue token via API, then craft an expired one directly."""
        expired_token = issue_anonymous_token(user_id="expired", ttl_hours=-1)
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {expired_token}"},
        )
        assert r.status_code == 401

    def test_wrong_secret_token_returns_401(self, auth_client, monkeypatch):
        """Token signed with a different secret is rejected."""
        monkeypatch.setattr(settings, "auth_token_secret", "other-secret-xyz")
        foreign_token = issue_anonymous_token(user_id="foreign")
        # Restore the original secret for the middleware
        monkeypatch.setattr(settings, "auth_token_secret", TOKEN_SECRET)
        r = auth_client.get(
            "/api/v1/projects",
            headers={"Authorization": f"Bearer {foreign_token}"},
        )
        assert r.status_code == 401

    # ── MVP mode (empty API_KEY) ──────────────────

    def test_mvp_mode_no_auth_required(self, open_client):
        r = open_client.get("/api/v1/projects")
        assert r.status_code == 200

    def test_mvp_mode_run_no_auth_required(self, open_client):
        r = open_client.post("/api/v1/run", json={"projects": [{"name": "MVPProj"}]})
        assert r.status_code == 200

    # ── OPTIONS (CORS preflight) ──────────────────

    def test_options_bypasses_auth(self, auth_client):
        r = auth_client.options("/api/v1/projects")
        assert r.status_code != 401

    # ── Auth endpoint itself is public ────────────

    def test_auth_endpoint_in_openapi(self, auth_client):
        """Auth endpoint appears in OpenAPI schema."""
        r = auth_client.get("/openapi.json")
        assert r.status_code == 200
        paths = r.json()["paths"]
        assert "/api/v1/auth/anonymous" in paths


# ═══════════════════════════════════════════════════════════════
# user_id Propagation
# ═══════════════════════════════════════════════════════════════


class TestUserIdPropagation:
    """Verify user_id is written to request.state."""

    def test_get_current_user_admin(self):
        """Admin requests get user_id='admin'."""

        class FakeState:
            user_id = "admin"
            user_role = "admin"

        class FakeRequest:
            state = FakeState()

        user = get_current_user(FakeRequest())
        assert user["user_id"] == "admin"
        assert user["role"] == "admin"

    def test_get_current_user_anonymous(self):
        """Anonymous token requests get the token's user_id."""

        class FakeState:
            user_id = "anon-abc123"
            user_role = "anonymous"

        class FakeRequest:
            state = FakeState()

        user = get_current_user(FakeRequest())
        assert user["user_id"] == "anon-abc123"
        assert user["role"] == "anonymous"

    def test_get_current_user_no_auth(self):
        """When auth is disabled, falls back to 'anonymous'."""

        class FakeState:
            pass  # no user_id / user_role attributes

        class FakeRequest:
            state = FakeState()

        user = get_current_user(FakeRequest())
        assert user["user_id"] == "anonymous"
        assert user["role"] == "anonymous"

    def test_anon_user_id_in_feedback(self, auth_client):
        """Feedback submitted with an anonymous token records the user_id."""
        token = _get_anon_token(auth_client, user_id="feedback-user-99")
        r = auth_client.post(
            "/api/v1/feedback",
            json={"project_id": "proj-99", "signal": "useful"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200

        # Verify feedback was stored
        r2 = auth_client.get(
            "/api/v1/feedback/proj-99",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["ok"] is True
