"""Unit tests for RBAC permission engine (W12-07, ADR-008 & ROADMAP §25.2, §25.7)."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.auth import (
    ALL_ROLES,
    ROLE_ADMIN,
    ROLE_ANALYST,
    ROLE_ANONYMOUS,
    ROLE_VIEWER,
    check_role_permission,
    require_role,
)


class TestRBACPermissionEngine:
    """Test check_role_permission logic across all roles."""

    def test_all_roles_constant(self) -> None:
        assert set(ALL_ROLES) == {"admin", "analyst", "viewer", "anonymous"}

    def test_public_endpoints_allowed_for_all_roles(self) -> None:
        public_cases = [
            ("GET", "/health"),
            ("GET", "/metrics"),
            ("GET", "/docs"),
            ("POST", "/api/v1/webhook/alchemy"),
            ("POST", "/api/v1/auth/anonymous"),
            ("POST", "/api/v1/auth/register"),
            ("POST", "/api/v1/auth/login"),
            ("POST", "/api/v1/auth/refresh"),
        ]
        for role in (*ALL_ROLES, "unknown_role"):
            for method, path in public_cases:
                allowed, reason = check_role_permission(role, method, path)
                assert allowed is True, f"Public endpoint {method} {path} should be allowed for role {role}"
                assert reason == ""

    def test_admin_role_has_full_access(self) -> None:
        admin_cases = [
            ("POST", "/api/v1/run"),
            ("POST", "/api/v1/re-score/1"),
            ("POST", "/api/v1/feedback"),
            ("GET", "/api/v1/projects"),
            ("GET", "/api/v1/settings"),
            ("POST", "/api/v1/quarantine"),
            ("POST", "/api/v1/export"),
            ("POST", "/api/v1/import"),
            ("POST", "/api/v1/collections/github/trigger"),
            ("PATCH", "/api/v1/projects/proj-1/funding"),
            ("POST", "/api/v1/watched-wallets"),
        ]
        for method, path in admin_cases:
            allowed, reason = check_role_permission(ROLE_ADMIN, method, path)
            assert allowed is True, f"Admin should be allowed for {method} {path}"
            assert reason == ""

    def test_analyst_role_permissions(self) -> None:
        # Analyst allowed operations
        allowed_cases = [
            ("GET", "/api/v1/projects"),
            ("GET", "/api/v1/projects/proj-1"),
            ("GET", "/api/v1/discoveries"),
            ("POST", "/api/v1/feedback"),
            ("POST", "/api/v1/feedback/batch"),
            ("POST", "/api/v1/re-score/1"),  # explicitly allowed for analyst (ADR-008 §2)
            ("POST", "/api/v1/watchlist/proj-1"),
            ("DELETE", "/api/v1/watchlist/proj-1"),
            ("POST", "/api/v1/interactions"),
            ("POST", "/api/v1/projects/proj-1/participation"),
            ("POST", "/api/v1/projects/proj-1/roi/entries"),
            ("POST", "/api/v1/events"),
            ("POST", "/api/v1/notifications/read"),
        ]
        for method, path in allowed_cases:
            allowed, reason = check_role_permission(ROLE_ANALYST, method, path)
            assert allowed is True, f"Analyst should be allowed for {method} {path}, got reason: {reason}"

        # Analyst forbidden operations (admin-only)
        forbidden_cases = [
            ("POST", "/api/v1/run"),
            ("GET", "/api/v1/settings"),
            ("GET", "/api/v1/archive"),
            ("GET", "/api/v1/scheduler"),
            ("POST", "/api/v1/notify"),
            ("POST", "/api/v1/watched-wallets"),
            ("POST", "/api/v1/quarantine"),
            ("POST", "/api/v1/export"),
            ("POST", "/api/v1/import"),
            ("POST", "/api/v1/collections/github/trigger"),
            ("PATCH", "/api/v1/collections/github"),
            ("PATCH", "/api/v1/projects/proj-1/funding"),
        ]
        for method, path in forbidden_cases:
            allowed, reason = check_role_permission(ROLE_ANALYST, method, path)
            assert allowed is False, f"Analyst should be forbidden for {method} {path}"
            assert "Admin access required" in reason

    def test_viewer_role_permissions(self) -> None:
        # Viewer allowed operations (read-only dashboard + reading helpers + auth)
        allowed_cases = [
            ("GET", "/api/v1/projects"),
            ("GET", "/api/v1/projects/proj-1"),
            ("GET", "/api/v1/discoveries"),
            ("GET", "/api/v1/timeline"),
            ("GET", "/api/v1/insights"),
            ("GET", "/api/v1/watchlist"),
            ("GET", "/api/v1/feedback"),
            ("GET", "/api/v1/interactions"),
            ("GET", "/api/v1/notifications"),
            ("GET", "/api/v1/auth/me"),
            ("POST", "/api/v1/auth/logout"),
            ("POST", "/api/v1/auth/logout/all"),
            ("POST", "/api/v1/projects/proj-1/ai-brief"),
            ("POST", "/api/v1/projects/proj-1/ai-chat"),
            ("POST", "/api/v1/events"),
            ("POST", "/api/v1/notifications/read"),
        ]
        for method, path in allowed_cases:
            allowed, reason = check_role_permission(ROLE_VIEWER, method, path)
            assert allowed is True, f"Viewer should be allowed for {method} {path}, got reason: {reason}"

        # Viewer forbidden operations (cannot run, cannot re-score, cannot submit feedback, cannot mutate)
        forbidden_cases = [
            ("POST", "/api/v1/run"),
            ("POST", "/api/v1/re-score/1"),
            ("POST", "/api/v1/feedback"),
            ("POST", "/api/v1/feedback/batch"),
            ("POST", "/api/v1/watchlist/proj-1"),
            ("DELETE", "/api/v1/watchlist/proj-1"),
            ("POST", "/api/v1/interactions"),
            ("PATCH", "/api/v1/interactions/int-1"),
            ("DELETE", "/api/v1/interactions/int-1"),
            ("POST", "/api/v1/projects/proj-1/skip"),
            ("DELETE", "/api/v1/projects/proj-1/skip"),
            ("POST", "/api/v1/projects/proj-1/participation"),
            ("POST", "/api/v1/participation/plan-1"),
            ("DELETE", "/api/v1/participation/plan-1"),
            ("POST", "/api/v1/projects/proj-1/roi/entries"),
            ("DELETE", "/api/v1/roi/entries/entry-1"),
            ("DELETE", "/api/v1/user-profile"),
            ("POST", "/api/v1/projects/proj-1/opportunity/evaluate"),
            ("POST", "/api/v1/projects/proj-1/opportunity/evidence"),
            ("GET", "/api/v1/settings"),
            ("POST", "/api/v1/collections/github/trigger"),
        ]
        for method, path in forbidden_cases:
            allowed, reason = check_role_permission(ROLE_VIEWER, method, path)
            assert allowed is False, f"Viewer should be forbidden for {method} {path}"

    def test_anonymous_role_permissions(self) -> None:
        # Anonymous allowed operations (V2 compatible)
        allowed_cases = [
            ("GET", "/api/v1/projects"),
            ("GET", "/api/v1/discoveries"),
            ("POST", "/api/v1/feedback"),
            ("POST", "/api/v1/feedback/batch"),
            ("POST", "/api/v1/events"),
            ("POST", "/api/v1/watchlist/proj-1"),
        ]
        for method, path in allowed_cases:
            allowed, reason = check_role_permission(ROLE_ANONYMOUS, method, path)
            assert allowed is True, f"Anonymous should be allowed for {method} {path}"

        # Anonymous forbidden operations (admin-only, run, re-score)
        forbidden_cases = [
            ("POST", "/api/v1/run"),
            ("POST", "/api/v1/re-score/1"),
            ("GET", "/api/v1/settings"),
            ("GET", "/api/v1/archive"),
            ("POST", "/api/v1/collections/github/trigger"),
        ]
        for method, path in forbidden_cases:
            allowed, reason = check_role_permission(ROLE_ANONYMOUS, method, path)
            assert allowed is False, f"Anonymous should be forbidden for {method} {path}"

    def test_unknown_role_is_rejected(self) -> None:
        allowed, reason = check_role_permission("superuser", "GET", "/api/v1/projects")
        assert allowed is False
        assert "not recognized" in reason


class TestRequireRoleDependency:
    """Test require_role FastAPI dependency helper."""

    def test_require_role_granted(self) -> None:
        dep = require_role(ROLE_ADMIN, ROLE_ANALYST)

        class MockRequest:
            class state:
                user_role = ROLE_ANALYST

        req = MockRequest()
        result = dep(req)  # type: ignore[arg-type]
        assert result == ROLE_ANALYST

    def test_require_role_denied(self) -> None:
        dep = require_role(ROLE_ADMIN)

        class MockRequest:
            class state:
                user_role = ROLE_VIEWER

        req = MockRequest()
        with pytest.raises(HTTPException) as exc_info:
            dep(req)  # type: ignore[arg-type]
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "FORBIDDEN"
