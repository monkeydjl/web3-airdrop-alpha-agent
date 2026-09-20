"""End-to-End integration tests for the V3 user system (W12-12).

Verifies the complete user system lifecycle across W12-06 through W12-11:
1. Registration & Bootstrap (admin bootstrap, viewer default, rbac promotion).
2. Authentication, Session Management, Token Refresh & Multi-device Logout.
3. User Preferences Lifecycle (GET -> PUT -> PATCH -> DELETE GDPR reset).
4. API Key Lifecycle & Authentication (create, list, auth via X-API-Key, revoke).
5. Business Operations & Row-Level Isolation (feedback, events, watchlist, skips, interactions).
6. RBAC Protection & Privilege Escalation Barriers.
7. GDPR Data Portability Export (GET /api/v1/user/data).
8. GDPR Account Deletion & Right to be Forgotten (feedback de-identification, data purge, re-registration).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app
from app.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def clean_auth_e2e_db(tmp_path, monkeypatch):
    """Ensure clean database tables before and after each test."""
    test_db = str(tmp_path / "user_system_e2e.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    monkeypatch.setattr(settings, "jwt_secret", "test-e2e-jwt-secret-at-least-32-chars-long!")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    monkeypatch.setattr(settings, "enable_events_tracking", True)

    from app.db import init_db

    init_db()

    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM watchlist")
        conn.execute("DELETE FROM project_skips")
        conn.execute("DELETE FROM interactions")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM projects")

        # Insert test projects as globally shared resources
        conn.execute(
            """
            INSERT INTO projects (
                id, name, sector, stage, score, label, confidence, url, created_at, updated_at
            ) VALUES
            ('e2e_proj_1', 'E2E Project One', 'DeFi', 'Mainnet', 91.0, 'FARM', 0.95, 'https://e2e1.io', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
            ('e2e_proj_2', 'E2E Project Two', 'Infra', 'Testnet', 72.0, 'WATCH', 0.80, 'https://e2e2.io', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        )
        conn.commit()

    yield

    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM watchlist")
        conn.execute("DELETE FROM project_skips")
        conn.execute("DELETE FROM interactions")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM projects")
        conn.commit()


@pytest.fixture
def client():
    return TestClient(create_app())


class TestUserSystemFullLifecycleE2E:
    """Complete end-to-end integration test of the user system."""

    def test_full_user_lifecycle_e2e(self, client: TestClient) -> None:
        # =========================================================================
        # Stage 1: Registration & Bootstrap
        # =========================================================================

        # 1.1 First user registers -> automatically bootstrapped as admin
        admin_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "admin@example.com",
                "password": "AdminPassword123",
                "display_name": "Admin User",
            },
        )
        assert admin_reg.status_code == 200
        admin_data = admin_reg.json()
        admin_token = admin_data["access_token"]
        admin_id = admin_data["user"]["id"]
        assert admin_data["user"]["role"] == "admin"
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # 1.2 Second user registers -> defaults to viewer
        analyst_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "analyst@example.com",
                "password": "AnalystPassword123",
                "display_name": "Analyst User",
            },
        )
        assert analyst_reg.status_code == 200
        analyst_data = analyst_reg.json()
        assert analyst_data["user"]["role"] == "viewer"
        analyst_id = analyst_data["user"]["id"]

        # 1.3 Admin promotes second user to 'analyst' in UserRepository
        with get_connection() as conn:
            user_repo = UserRepository(conn)
            user_repo.update_role(analyst_id, "analyst")

        # 1.4 Third user registers -> viewer
        viewer_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "viewer@example.com",
                "password": "ViewerPassword123",
                "display_name": "Viewer User",
            },
        )
        assert viewer_reg.status_code == 200
        viewer_data = viewer_reg.json()
        assert viewer_data["user"]["role"] == "viewer"
        viewer_id = viewer_data["user"]["id"]

        # 1.5 Registration validation: duplicate email rejected
        dup_reg = client.post(
            "/api/v1/auth/register",
            json={"email": "viewer@example.com", "password": "Password123"},
        )
        assert dup_reg.status_code == 400
        assert dup_reg.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

        # 1.6 Registration validation: weak password rejected
        weak_reg = client.post(
            "/api/v1/auth/register",
            json={"email": "weak@example.com", "password": "weak"},
        )
        assert weak_reg.status_code == 400
        assert weak_reg.json()["error"]["code"] == "WEAK_PASSWORD"

        # =========================================================================
        # Stage 2: Authentication, Session Management, Refresh & Multi-device Logout
        # =========================================================================

        # 2.1 Viewer logs in (Device A)
        login_dev_a = client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "ViewerPassword123"},
        )
        assert login_dev_a.status_code == 200
        dev_a_token = login_dev_a.json()["access_token"]
        dev_a_refresh = login_dev_a.json()["refresh_token"]
        dev_a_headers = {"Authorization": f"Bearer {dev_a_token}"}

        # 2.2 Verify identity via /auth/me
        me_res = client.get("/api/v1/auth/me", headers=dev_a_headers)
        assert me_res.status_code == 200
        assert me_res.json()["id"] == viewer_id
        assert me_res.json()["role"] == "viewer"
        assert me_res.json()["email"] == "viewer@example.com"

        # 2.3 Token refresh
        refresh_res = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": dev_a_refresh},
        )
        assert refresh_res.status_code == 200
        refreshed_token = refresh_res.json()["access_token"]
        refreshed_headers = {"Authorization": f"Bearer {refreshed_token}"}

        # 2.4 Multi-device login: Viewer logs in on Device B
        login_dev_b = client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "ViewerPassword123"},
        )
        assert login_dev_b.status_code == 200
        dev_b_token = login_dev_b.json()["access_token"]
        dev_b_refresh = login_dev_b.json()["refresh_token"]
        dev_b_headers = {"Authorization": f"Bearer {dev_b_token}"}

        # 2.5 Multi-device logout: revokes all sessions
        logout_all_res = client.post("/api/v1/auth/logout/all", headers=dev_b_headers)
        assert logout_all_res.status_code == 200
        assert logout_all_res.json()["data"]["revoked_sessions"] >= 2

        # 2.6 Verify Device B access token is blacklisted
        assert client.get("/api/v1/auth/me", headers=dev_b_headers).status_code == 401

        # 2.7 Verify all sessions revoked: refresh tokens from Device A and Device B both fail (401)
        res_ref_a = client.post("/api/v1/auth/refresh", json={"refresh_token": dev_a_refresh})
        assert res_ref_a.status_code == 401
        assert res_ref_a.json()["error"]["code"] == "SESSION_REVOKED"

        res_ref_b = client.post("/api/v1/auth/refresh", json={"refresh_token": dev_b_refresh})
        assert res_ref_b.status_code == 401
        assert res_ref_b.json()["error"]["code"] == "SESSION_REVOKED"

        # =========================================================================
        # Stage 3: User Preferences Lifecycle
        # =========================================================================

        # 3.1 Viewer logs back in
        viewer_login = client.post(
            "/api/v1/auth/login",
            json={"email": "viewer@example.com", "password": "ViewerPassword123"},
        )
        assert viewer_login.status_code == 200
        viewer_token = viewer_login.json()["access_token"]
        viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

        # 3.2 GET preferences -> defaults
        pref_get_default = client.get("/api/v1/user/preferences", headers=viewer_headers)
        assert pref_get_default.status_code == 200
        assert pref_get_default.json()["data"]["theme"] == "dark"
        assert pref_get_default.json()["data"]["risk_tolerance"] == 0.5

        # 3.3 PUT preferences -> full replacement
        pref_put = client.put(
            "/api/v1/user/preferences",
            headers=viewer_headers,
            json={
                "theme": "light",
                "language": "en",
                "risk_tolerance": 0.75,
                "notifications": {"email": True, "telegram": False},
            },
        )
        assert pref_put.status_code == 200
        assert pref_put.json()["data"]["theme"] == "light"
        assert pref_put.json()["data"]["risk_tolerance"] == 0.75

        # 3.4 PATCH preferences -> partial merge
        pref_patch = client.patch(
            "/api/v1/user/preferences",
            headers=viewer_headers,
            json={"risk_tolerance": 0.40, "theme": "dark"},
        )
        assert pref_patch.status_code == 200
        patched = pref_patch.json()["data"]
        assert patched["theme"] == "dark"  # updated
        assert patched["risk_tolerance"] == 0.40  # updated
        assert patched["language"] == "en"  # preserved

        # 3.5 DELETE preferences -> GDPR reset
        pref_del = client.delete("/api/v1/user/preferences", headers=viewer_headers)
        assert pref_del.status_code == 200
        assert pref_del.json()["data"]["theme"] == "dark"
        assert pref_del.json()["data"]["risk_tolerance"] == 0.5

        # =========================================================================
        # Stage 4: API Key Lifecycle & Authentication
        # =========================================================================

        # 4.1 Analyst logs in (role was promoted to analyst)
        analyst_login = client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@example.com", "password": "AnalystPassword123"},
        )
        assert analyst_login.status_code == 200
        assert analyst_login.json()["user"]["role"] == "analyst"
        analyst_token = analyst_login.json()["access_token"]
        analyst_headers = {"Authorization": f"Bearer {analyst_token}"}

        # 4.2 Analyst creates API Key
        key_create = client.post(
            "/api/v1/api-keys",
            headers=analyst_headers,
            json={"name": "analyst-data-pipeline", "expires_in_days": 60},
        )
        assert key_create.status_code == 200
        raw_key = key_create.json()["data"]["raw_key"]
        key_id = key_create.json()["data"]["key"]["id"]
        assert raw_key.startswith("ak_")
        assert key_create.json()["data"]["key"]["role"] == "analyst"

        # 4.3 Analyst lists keys -> masked
        key_list = client.get("/api/v1/api-keys", headers=analyst_headers)
        assert key_list.status_code == 200
        keys = key_list.json()["data"]
        assert len(keys) == 1
        assert keys[0]["id"] == key_id
        assert "raw_key" not in keys[0]
        assert "key_hash" not in keys[0]

        # 4.4 Use API Key to authenticate via X-API-Key header
        api_key_headers = {"X-API-Key": raw_key}
        key_fb = client.post(
            "/api/v1/feedback",
            headers=api_key_headers,
            json={"project_id": "e2e_proj_1", "signal": "useful", "note": "Analyst feedback via API Key"},
        )
        assert key_fb.status_code == 200

        # 4.5 Revoke API Key
        key_revoke = client.delete(f"/api/v1/api-keys/{key_id}", headers=analyst_headers)
        assert key_revoke.status_code == 200

        # 4.6 Revoked key cannot authenticate
        key_fb_revoked = client.post(
            "/api/v1/feedback",
            headers=api_key_headers,
            json={"project_id": "e2e_proj_1", "signal": "useless"},
        )
        assert key_fb_revoked.status_code == 401

        # =========================================================================
        # Stage 5: Business Operations, RBAC Enforcement & Row-Level Data Isolation
        # =========================================================================

        # 5.1 Viewer is restricted from writing business records (RBAC: Viewer is read-only)
        assert client.post(
            "/api/v1/feedback",
            headers=viewer_headers,
            json={"project_id": "e2e_proj_1", "signal": "useful"},
        ).status_code == 403

        assert client.post(
            "/api/v1/watchlist/e2e_proj_1",
            headers=viewer_headers,
            json={"note": "Viewer watching"},
        ).status_code == 403

        assert client.post(
            "/api/v1/projects/e2e_proj_2/skip",
            headers=viewer_headers,
            json={"reason": "Viewer skipping"},
        ).status_code == 403

        assert client.post(
            "/api/v1/interactions",
            headers=viewer_headers,
            json={"project_id": "e2e_proj_1", "status": "active"},
        ).status_code == 403

        # But Viewer CAN submit telemetry/click events
        viewer_ev = client.post(
            "/api/v1/events",
            headers=viewer_headers,
            json={"project_id": "e2e_proj_1", "event_type": "click", "detail": '{"target": "docs"}'},
        )
        assert viewer_ev.status_code == 200

        # 5.2 Analyst creates business records on analyst_headers (Feedback already created in 4.4)
        # Event on e2e_proj_1
        client.post(
            "/api/v1/events",
            headers=analyst_headers,
            json={"project_id": "e2e_proj_1", "event_type": "view", "detail": '{"tab": "tokenomics"}'},
        )
        # Watchlist on e2e_proj_1
        client.post(
            "/api/v1/watchlist/e2e_proj_1",
            headers=analyst_headers,
            json={"note": "Analyst watching proj 1"},
        )
        # Skip on e2e_proj_2
        client.post(
            "/api/v1/projects/e2e_proj_2/skip",
            headers=analyst_headers,
            json={"reason": "Analyst skipping proj 2"},
        )
        # Interaction on e2e_proj_1
        client.post(
            "/api/v1/interactions",
            headers=analyst_headers,
            json={"project_id": "e2e_proj_1", "status": "active"},
        )

        # 5.3 Admin creates business records on admin_headers
        client.post(
            "/api/v1/feedback",
            headers=admin_headers,
            json={"project_id": "e2e_proj_2", "signal": "useless", "note": "Admin cautions proj 2"},
        )
        client.post(
            "/api/v1/events",
            headers=admin_headers,
            json={"project_id": "e2e_proj_2", "event_type": "expand", "detail": '{"sec": "team"}'},
        )
        client.post(
            "/api/v1/watchlist/e2e_proj_2",
            headers=admin_headers,
            json={"note": "Admin watching proj 2"},
        )
        client.post(
            "/api/v1/projects/e2e_proj_1/skip",
            headers=admin_headers,
            json={"reason": "Admin skipping proj 1"},
        )
        client.post(
            "/api/v1/interactions",
            headers=admin_headers,
            json={"project_id": "e2e_proj_2", "status": "active"},
        )

        # 5.4 Verify Analyst row-level isolation
        a_fb = client.get("/api/v1/feedback/e2e_proj_1", headers=analyst_headers).json()["data"]
        assert a_fb["count"] == 1
        assert a_fb["items"][0]["note"] == "Analyst feedback via API Key"

        a_fb_2 = client.get("/api/v1/feedback/e2e_proj_2", headers=analyst_headers).json()["data"]
        assert a_fb_2["count"] == 0  # Admin's feedback on proj 2 not visible to Analyst

        a_events = client.get("/api/v1/events", headers=analyst_headers).json()["data"]
        assert a_events["total"] == 1
        assert a_events["items"][0]["project_id"] == "e2e_proj_1"

        a_wl = client.get("/api/v1/watchlist", headers=analyst_headers).json()["data"]
        assert a_wl["total"] == 1
        assert a_wl["items"][0]["project_id"] == "e2e_proj_1"

        # 5.5 Verify Viewer row-level isolation
        v_fb = client.get("/api/v1/feedback/e2e_proj_1", headers=viewer_headers).json()["data"]
        assert v_fb["count"] == 0

        v_events = client.get("/api/v1/events", headers=viewer_headers).json()["data"]
        assert v_events["total"] == 1
        assert v_events["items"][0]["project_id"] == "e2e_proj_1"
        assert v_events["items"][0]["event_type"] == "click"

        v_wl = client.get("/api/v1/watchlist", headers=viewer_headers).json()["data"]
        assert v_wl["total"] == 0

        # 5.6 Admin queries: can view all
        adm_fb_1 = client.get("/api/v1/feedback/e2e_proj_1", headers=admin_headers).json()["data"]
        assert adm_fb_1["count"] == 1
        adm_fb_2 = client.get("/api/v1/feedback/e2e_proj_2", headers=admin_headers).json()["data"]
        assert adm_fb_2["count"] == 1

        # Admin filters by user_id
        adm_filtered = client.get(f"/api/v1/feedback/e2e_proj_1?user_id={analyst_id}", headers=admin_headers).json()["data"]
        assert adm_filtered["count"] == 1
        assert adm_filtered["items"][0]["note"] == "Analyst feedback via API Key"

        # 5.7 Global shared data: projects table accessible identically
        p_v = client.get("/api/v1/projects", headers=viewer_headers).json()["data"]["projects"]
        p_a = client.get("/api/v1/projects", headers=analyst_headers).json()["data"]["projects"]
        p_adm = client.get("/api/v1/projects", headers=admin_headers).json()["data"]["projects"]
        assert len(p_v) == len(p_a) == len(p_adm) == 2

        # =========================================================================
        # Stage 6: RBAC Protection & Escalation Barriers
        # =========================================================================

        # 6.1 Viewer calling admin-only settings endpoint -> 403
        viewer_admin_call = client.get("/api/v1/settings/config", headers=viewer_headers)
        assert viewer_admin_call.status_code == 403
        assert viewer_admin_call.json()["error"]["code"] == "FORBIDDEN"

        # 6.2 Analyst calling admin-only settings endpoint -> 403
        analyst_admin_call = client.get("/api/v1/settings/config", headers=analyst_headers)
        assert analyst_admin_call.status_code == 403
        assert analyst_admin_call.json()["error"]["code"] == "FORBIDDEN"

        # 6.3 Admin calling admin-only settings endpoint -> 200
        admin_settings_call = client.get("/api/v1/settings/config", headers=admin_headers)
        assert admin_settings_call.status_code == 200

        # =========================================================================
        # Stage 7: GDPR Data Portability Export
        # =========================================================================

        # 7.1 Analyst exports complete personal data bundle
        export_res = client.get("/api/v1/user/data", headers=analyst_headers)
        assert export_res.status_code == 200
        exported = export_res.json()["data"]

        # Verify export structure
        assert exported["user"]["id"] == analyst_id
        assert exported["user"]["email"] == "analyst@example.com"
        assert "password_hash" not in exported["user"]

        assert isinstance(exported["preferences"], dict)

        assert len(exported["feedback"]) == 1
        assert exported["feedback"][0]["project_id"] == "e2e_proj_1"

        assert len(exported["events"]) == 1
        assert exported["events"][0]["project_id"] == "e2e_proj_1"

        assert len(exported["watchlist"]) == 1
        assert exported["watchlist"][0]["project_id"] == "e2e_proj_1"

        assert len(exported["project_skips"]) == 1
        assert exported["project_skips"][0]["project_id"] == "e2e_proj_2"

        assert len(exported["interactions"]) == 1
        assert exported["interactions"][0]["project_id"] == "e2e_proj_1"

        # =========================================================================
        # Stage 8: GDPR Account Deletion & Right to be Forgotten
        # =========================================================================

        # 8.1 Analyst deletes account
        del_res = client.delete("/api/v1/user/account", headers=analyst_headers)
        assert del_res.status_code == 200
        assert del_res.json()["data"]["status"] == "deleted"

        # 8.2 Analyst's JWT token is immediately rejected
        assert client.get("/api/v1/auth/me", headers=analyst_headers).status_code == 401
        assert client.get("/api/v1/user/data", headers=analyst_headers).status_code == 401

        # 8.3 Database state verification:
        with get_connection() as conn:
            # Feedback retained but de-identified (user_id is NULL)
            fb_rows = conn.execute(
                "SELECT user_id, project_id, signal FROM feedback WHERE project_id = 'e2e_proj_1'"
            ).fetchall()
            assert len(fb_rows) == 1
            assert fb_rows[0][0] is None  # user_id is NULL
            assert fb_rows[0][1] == "e2e_proj_1"
            assert fb_rows[0][2] == "useful"

            # Events hard deleted for analyst
            events_cnt = conn.execute(
                "SELECT COUNT(*) FROM events WHERE user_id = ?", (analyst_id,)
            ).fetchone()[0]
            assert events_cnt == 0

            # Viewer's event on e2e_proj_1 still exists
            viewer_events_cnt = conn.execute(
                "SELECT COUNT(*) FROM events WHERE user_id = ?", (viewer_id,)
            ).fetchone()[0]
            assert viewer_events_cnt == 1

            # Watchlist hard deleted
            wl_cnt = conn.execute(
                "SELECT COUNT(*) FROM watchlist WHERE user_id = ?", (analyst_id,)
            ).fetchone()[0]
            assert wl_cnt == 0

            # Skips hard deleted
            skip_cnt = conn.execute(
                "SELECT COUNT(*) FROM project_skips WHERE user_id = ?", (analyst_id,)
            ).fetchone()[0]
            assert skip_cnt == 0

            # Interactions hard deleted
            interact_cnt = conn.execute(
                "SELECT COUNT(*) FROM interactions WHERE user_id = ?", (analyst_id,)
            ).fetchone()[0]
            assert interact_cnt == 0

            # User record deleted
            user_row = conn.execute("SELECT id FROM users WHERE id = ?", (analyst_id,)).fetchone()
            assert user_row is None

        # 8.4 Re-registration: The same email can immediately register a new clean account
        re_reg = client.post(
            "/api/v1/auth/register",
            json={
                "email": "analyst@example.com",
                "password": "NewAnalystPassword123",
                "display_name": "Analyst Reborn",
            },
        )
        assert re_reg.status_code == 200
        new_analyst_data = re_reg.json()
        assert new_analyst_data["user"]["id"] != analyst_id
        assert new_analyst_data["user"]["display_name"] == "Analyst Reborn"


class TestUserSystemConcurrencyAndEdgeCases:
    """Edge cases, anonymous boundaries, and token replay prevention."""

    def test_anonymous_user_boundaries(self, client: TestClient) -> None:
        """Verify anonymous tokens cannot access personal data or admin endpoints."""
        anon_res = client.post("/api/v1/auth/anonymous")
        assert anon_res.status_code == 200
        anon_token = anon_res.json()["access_token"]
        anon_headers = {"Authorization": f"Bearer {anon_token}"}

        # /auth/me returns 401 for anonymous
        assert client.get("/api/v1/auth/me", headers=anon_headers).status_code == 401

        # /user/preferences returns 401
        assert client.get("/api/v1/user/preferences", headers=anon_headers).status_code == 401
        assert client.put("/api/v1/user/preferences", headers=anon_headers, json={}).status_code == 401

        # /api-keys returns 401
        assert client.get("/api/v1/api-keys", headers=anon_headers).status_code == 401

        # GDPR export & deletion returns 401
        assert client.get("/api/v1/user/data", headers=anon_headers).status_code == 401
        assert client.delete("/api/v1/user/account", headers=anon_headers).status_code == 401

        # Admin settings returns 403
        assert client.get("/api/v1/settings/config", headers=anon_headers).status_code == 403

    def test_revoked_session_and_blacklisted_jwt_replay(self, client: TestClient) -> None:
        """Verify revoked sessions and blacklisted JWTs cannot be reused."""
        reg = client.post(
            "/api/v1/auth/register",
            json={"email": "replay@example.com", "password": "Password123"},
        )
        assert reg.status_code == 200
        access_token = reg.json()["access_token"]
        refresh_token = reg.json()["refresh_token"]
        headers = {"Authorization": f"Bearer {access_token}"}

        # Logout with refresh_token
        logout_res = client.post(
            "/api/v1/auth/logout",
            headers=headers,
            json={"refresh_token": refresh_token},
        )
        assert logout_res.status_code == 200

        # 1. Access token was blacklisted -> 401
        res_me = client.get("/api/v1/auth/me", headers=headers)
        assert res_me.status_code == 401

        # 2. Refresh token session was revoked -> 401
        res_refresh = client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        assert res_refresh.status_code == 401
        assert res_refresh.json()["error"]["code"] in ("SESSION_REVOKED", "INVALID_REFRESH_TOKEN")

    def test_cross_user_api_key_isolation(self, client: TestClient) -> None:
        """Verify User B cannot delete or see User A's API Keys."""
        # Register User A (admin)
        reg_a = client.post(
            "/api/v1/auth/register",
            json={"email": "usera@example.com", "password": "Password123"},
        )
        token_a = reg_a.json()["access_token"]
        headers_a = {"Authorization": f"Bearer {token_a}"}

        # User A creates API key
        key_a_res = client.post(
            "/api/v1/api-keys",
            headers=headers_a,
            json={"name": "user-a-key"},
        )
        assert key_a_res.status_code == 200
        key_a_id = key_a_res.json()["data"]["key"]["id"]

        # Register User B (viewer)
        reg_b = client.post(
            "/api/v1/auth/register",
            json={"email": "userb@example.com", "password": "Password123"},
        )
        token_b = reg_b.json()["access_token"]
        headers_b = {"Authorization": f"Bearer {token_b}"}

        # User B cannot see User A's key
        b_keys = client.get("/api/v1/api-keys", headers=headers_b).json()["data"]
        assert len(b_keys) == 0

        # User B cannot delete User A's key -> 404
        del_res = client.delete(f"/api/v1/api-keys/{key_a_id}", headers=headers_b)
        assert del_res.status_code == 404
