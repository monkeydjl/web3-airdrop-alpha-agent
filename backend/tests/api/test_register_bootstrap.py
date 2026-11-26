"""注册自举防护回归（2026-11-13 审查 H-2）。

背景：`/auth/register` 在 PUBLIC_PREFIXES，而端点此前无条件执行
"首位注册用户自举为 admin"。公网新部署时攻击者抢注即得永久 admin，
且注册无任何邀请机制、可无限批量注册灌库。

契约：
- ALLOW_REGISTRATION=false → 注册整体 403；
- REGISTRATION_BOOTSTRAP_TOKEN 配置后，首位 admin 只发给携带正确 token
  的请求（fail-closed：token 不对就不建用户，自举名额不被消费）；
- 生产环境（APP_ENV=production）两者都没配 → 首位用户降级 viewer，
  运维走 bootstrap token 路径创建 admin；
- 开发/测试环境无 token 时保持原自举行为（DX 不变）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_auth_tables():
    """首位自举判定依赖 user_count == 0，每个用例前后清空 users/sessions/jti。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM users")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM users")
        conn.commit()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _register(client: TestClient, email: str = "ops@example.com", **extra: str) -> dict:
    payload: dict = {"email": email, "password": "Password123", **extra}
    return client.post("/api/v1/auth/register", json=payload).json()


def test_first_user_admin_in_test_env_without_bootstrap(client: TestClient) -> None:
    """开发/测试环境无 bootstrap token：保持原自举行为（DX 不变）。"""
    data = _register(client)
    assert data["user"]["role"] == "admin"


def test_registration_disabled_returns_403(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "allow_registration", False)
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "nobody@example.com", "password": "Password123"},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "REGISTRATION_DISABLED"


def test_production_without_bootstrap_degrades_first_user_to_viewer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产 + 未配 bootstrap token：首位用户不再自举 admin（防抢注）。"""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "registration_bootstrap_token", "")
    data = _register(client)
    assert data["user"]["role"] == "viewer"


def test_production_with_bootstrap_requires_matching_token(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """生产 + 已配 bootstrap token：不携带 / 携带错误 token 一律 403，且不建用户。"""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "registration_bootstrap_token", "ops-one-time-token")

    missing = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "Password123"},
    )
    assert missing.status_code == 403
    assert missing.json()["error"]["code"] == "BOOTSTRAP_TOKEN_REQUIRED"

    wrong = client.post(
        "/api/v1/auth/register",
        json={
            "email": "b@example.com",
            "password": "Password123",
            "bootstrap_token": "wrong-token",
        },
    )
    assert wrong.status_code == 403


def test_bootstrap_token_grants_admin_and_slot_survives_wrong_attempts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """生产 + 正确 bootstrap token → admin；错误尝试不消费自举名额。"""
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "registration_bootstrap_token", "ops-one-time-token")

    # 先来两次错误尝试（都不建用户）
    client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "Password123"},
    )
    client.post(
        "/api/v1/auth/register",
        json={
            "email": "b@example.com",
            "password": "Password123",
            "bootstrap_token": "wrong-token",
        },
    )

    data = _register(client, bootstrap_token="ops-one-time-token")
    assert data["user"]["role"] == "admin"

    # 自举完成后，后续注册回到 viewer
    second = _register(client, email="late@example.com")
    assert second["user"]["role"] == "viewer"


def test_bootstrap_grant_also_applies_outside_production(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """配置了 bootstrap token 的非生产环境同样走校验（配置即生效，不分环境）。"""
    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "registration_bootstrap_token", "ops-one-time-token")

    wrong = client.post(
        "/api/v1/auth/register",
        json={"email": "a@example.com", "password": "Password123"},
    )
    assert wrong.status_code == 403

    data = _register(client, bootstrap_token="ops-one-time-token")
    assert data["user"]["role"] == "admin"
