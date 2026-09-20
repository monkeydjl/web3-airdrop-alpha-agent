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


def _get_anon_token(client: TestClient) -> str:
    """Helper: issue an anonymous token via the API."""
    r = client.post("/api/v1/auth/anonymous")
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

    def test_client_user_id_is_ignored(self, auth_client):
        """调用方自报的 user_id 必须被忽略，身份一律服务端生成。

        本端点在公开路径里 —— 若接受客户端指定 user_id，任何人都能给
        别人的 user_id 签 token，从而读写按 user_id 隔离的 watchlist /
        feedback / interactions 数据（2026-08-30 安全审核修复）。
        """
        r = auth_client.post(
            "/api/v1/auth/anonymous",
            json={"user_id": "dashboard-user-42"},
        )
        assert r.status_code == 200
        issued = r.json()["user_id"]
        assert issued.startswith("anon-")
        assert issued != "dashboard-user-42"

        # 两次签发必须拿到不同身份 —— 服务端生成，不是调用方可控的固定值
        r2 = auth_client.post("/api/v1/auth/anonymous")
        assert r2.status_code == 200
        assert r2.json()["user_id"] != issued

    def test_request_body_is_optional(self, auth_client):
        """无请求体、空 JSON、带未知字段都应 200（请求体无任何字段）。"""
        assert auth_client.post("/api/v1/auth/anonymous").status_code == 200
        assert auth_client.post("/api/v1/auth/anonymous", json={}).status_code == 200
        assert auth_client.post("/api/v1/auth/anonymous", json={"user_id": "x"}).status_code == 200

    def test_issue_works_in_mvp_mode(self, open_client):
        """Token issuance works even when API_KEY is empty."""
        r = open_client.post("/api/v1/auth/anonymous")
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_issued_token_is_verifiable(self, auth_client):
        """Token returned by the endpoint passes verify_token()."""
        token = _get_anon_token(auth_client)
        payload = verify_token(token)
        assert payload is not None
        assert payload["user_id"].startswith("anon-")
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
        token = _get_anon_token(auth_client)
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

    # ── 按方法锁：同一路径读开放、写受限（2026-08-24 关掉的两个口子）──
    #
    # 这两处此前实测**匿名 token 返回 200**，而且不是"能看"而是"能做"：
    #   - trigger 真的会跑一次采集，写三张表、消耗第三方 API 配额
    #   - PATCH funding 改数据并触发重算
    # 但它们的 GET 是普通只读信息（采集源就绪状态 / 融资明细），首页在用，
    # 所以不能整前缀锁 —— 用 `ADMIN_ONLY_METHOD_RULES` 按方法分开。

    def test_anon_token_blocked_from_collection_trigger(self, auth_client):
        """匿名不能触发采集 —— 这是**会真的花钱**的操作。"""
        token = _get_anon_token(auth_client)
        r = auth_client.post(
            "/api/v1/collections/defillama/trigger",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, (
            f"匿名 token 触发采集拿到 {r.status_code} —— 这个端点会真的跑一次采集并消耗第三方配额。"
        )
        assert r.json()["error"]["code"] == "FORBIDDEN"

    def test_anon_token_blocked_from_collection_patch(self, auth_client):
        """匿名不能改采集源配置（开关、cron）。"""
        token = _get_anon_token(auth_client)
        r = auth_client.patch(
            "/api/v1/collections/defillama",
            json={"enabled": False},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, f"匿名 token 改采集源配置拿到 {r.status_code} —— 应当 403。"

    def test_anon_token_blocked_from_funding_patch(self, auth_client):
        """匿名不能改融资数据（会触发重算）。"""
        token = _get_anon_token(auth_client)
        r = auth_client.patch(
            "/api/v1/projects/some-project/funding",
            json={"total_funding_usd": 1},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 403, f"匿名 token 改融资数据拿到 {r.status_code} —— 应当 403。"

    def test_anon_token_still_reads_collection_sources(self, auth_client):
        """反向断言：只读的采集源列表**必须**保持对匿名开放。

        这条和上面三条一样重要。只写"该锁的锁上了"是半个断言 ——
        把整个 `/api/v1/collections` 前缀塞进 `ADMIN_ONLY_PREFIXES` 也能让
        上面三条全绿，代价是首页和 /discoveries 页对匿名角色直接空掉。
        **一个只验证"锁住了"的测试，无法区分"锁对了"和"锁多了"。**
        """
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/collections/sources",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 200, f"匿名读采集源列表拿到 {r.status_code} —— 这是只读的就绪状态，首页在用，不该锁。"

    def test_anon_token_still_reads_funding(self, auth_client):
        """反向断言：`GET .../funding` 必须保持对匿名开放。

        404（项目不存在）是可以的，401/403 说明被鉴权挡住了 —— 那才是回归。
        """
        token = _get_anon_token(auth_client)
        r = auth_client.get(
            "/api/v1/projects/some-project/funding",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code not in (401, 403), (
            f"匿名读融资明细被鉴权挡住了（{r.status_code}）—— 只有 PATCH 该锁，GET 不该。"
        )

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
        """Feedback submitted with an anonymous token records the user_id.

        user_id 由服务端签发（`anon-<hex>`）并写进 token；feedback 存储
        的是 token 里的身份，而不是调用方自报的字符串。
        """
        token = _get_anon_token(auth_client)
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
