"""API integration tests for User Preferences endpoints (W12-08, ROADMAP §25.6, §25.10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_auth_db():
    """Ensure clean auth tables before and after each test."""
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
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    with TestClient(create_app()) as c:
        yield c


def test_preferences_unauthenticated_and_anonymous(client: TestClient) -> None:
    """未认证请求与匿名 Token 访问偏好接口统一返回 401。"""
    # 1. 无凭据
    for method in ("GET", "DELETE"):
        res = client.request(method, "/api/v1/user/preferences")
        assert res.status_code == 401, f"{method} without auth expected 401, got {res.status_code}"
    for method in ("PUT", "PATCH"):
        res = client.request(method, "/api/v1/user/preferences", json={})
        assert res.status_code == 401, f"{method} without auth expected 401, got {res.status_code}"

    # 2. 匿名 Token (V2 HMAC)
    anon_res = client.post("/api/v1/auth/anonymous")
    assert anon_res.status_code == 200
    anon_token = anon_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {anon_token}"}

    res = client.get("/api/v1/user/preferences", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"

    res = client.put("/api/v1/user/preferences", headers=headers, json={"language": "en"})
    assert res.status_code == 401

    res = client.patch("/api/v1/user/preferences", headers=headers, json={"theme": "light"})
    assert res.status_code == 401

    res = client.delete("/api/v1/user/preferences", headers=headers)
    assert res.status_code == 401


def test_preferences_crud_flow(client: TestClient) -> None:
    """完整验证用户偏好的 CRUD 流程：GET默认 -> PUT全量 -> PATCH增量 -> DELETE重置。"""
    # 注册普通用户
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "Password123", "display_name": "Alice"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 1. GET: 首次获取返回默认偏好
    res = client.get("/api/v1/user/preferences", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["sector_preferences"] == {}
    assert data["risk_tolerance"] == 0.5
    assert data["language"] == "zh"
    assert data["theme"] == "dark"

    # 2. PUT: 全量更新偏好
    put_payload = {
        "sector_preferences": {"L2": 1.4, "DeFi": 0.8},
        "risk_tolerance": 0.75,
        "preferred_stage": ["testnet", "mainnet"],
        "notifications": {"telegram": "@alice_crypto", "daily_digest": True},
        "language": "en",
        "theme": "light",
    }
    put_res = client.put("/api/v1/user/preferences", headers=headers, json=put_payload)
    assert put_res.status_code == 200
    assert put_res.json()["data"]["sector_preferences"] == {"L2": 1.4, "DeFi": 0.8}
    assert put_res.json()["data"]["risk_tolerance"] == 0.75
    assert put_res.json()["data"]["language"] == "en"
    assert put_res.json()["data"]["theme"] == "light"

    # GET 再次确认持久化成功
    get_res = client.get("/api/v1/user/preferences", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["data"]["sector_preferences"] == {"L2": 1.4, "DeFi": 0.8}
    assert get_res.json()["data"]["notifications"]["telegram"] == "@alice_crypto"

    # 3. PATCH: 增量合并更新
    patch_payload = {
        "risk_tolerance": 0.3,
        "sector_preferences": {"AI": 1.8},
        "theme": "dark",
    }
    patch_res = client.patch("/api/v1/user/preferences", headers=headers, json=patch_payload)
    assert patch_res.status_code == 200
    patch_data = patch_res.json()["data"]
    # risk_tolerance 与 theme 已被更新
    assert patch_data["risk_tolerance"] == 0.3
    assert patch_data["theme"] == "dark"
    # sector_preferences 字典浅合并，包含 L2, DeFi 以及新增的 AI
    assert patch_data["sector_preferences"] == {"L2": 1.4, "DeFi": 0.8, "AI": 1.8}
    # 未在 PATCH 中指定的字段（language, preferred_stage, notifications）被完整保留
    assert patch_data["language"] == "en"
    assert patch_data["preferred_stage"] == ["testnet", "mainnet"]
    assert patch_data["notifications"]["daily_digest"] is True

    # 4. DELETE: 清除重置偏好为默认值（GDPR §25.9）
    del_res = client.delete("/api/v1/user/preferences", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["sector_preferences"] == {}
    assert del_res.json()["data"]["risk_tolerance"] == 0.5
    assert del_res.json()["data"]["language"] == "zh"
    assert del_res.json()["data"]["theme"] == "dark"

    # GET 再次确认已被清除
    get_res2 = client.get("/api/v1/user/preferences", headers=headers)
    assert get_res2.status_code == 200
    assert get_res2.json()["data"]["sector_preferences"] == {}
    assert get_res2.json()["data"]["risk_tolerance"] == 0.5


def test_preferences_user_isolation(client: TestClient) -> None:
    """验证多用户之间的偏好严格隔离，用户 A 修改不污染用户 B。"""
    # 注册用户 A (首个注册自举为 admin)
    res_a = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "Password123", "display_name": "Alice"},
    )
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 注册用户 B (后续注册默认为 viewer)
    res_b = client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "Password123", "display_name": "Bob"},
    )
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 用户 A 设置偏好
    client.put(
        "/api/v1/user/preferences",
        headers=headers_a,
        json={"sector_preferences": {"L2": 1.9}, "risk_tolerance": 0.9, "language": "en", "theme": "light"},
    )

    # 用户 B 查看自身偏好，应依然为默认值
    res_b_get = client.get("/api/v1/user/preferences", headers=headers_b)
    assert res_b_get.status_code == 200
    b_data = res_b_get.json()["data"]
    assert b_data["sector_preferences"] == {}
    assert b_data["risk_tolerance"] == 0.5
    assert b_data["language"] == "zh"
    assert b_data["theme"] == "dark"

    # 用户 B 设置自身偏好
    client.put(
        "/api/v1/user/preferences",
        headers=headers_b,
        json={"sector_preferences": {"GameFi": 0.3}, "risk_tolerance": 0.1, "language": "zh", "theme": "dark"},
    )

    # 再次验证用户 A 偏好未被改变
    res_a_get = client.get("/api/v1/user/preferences", headers=headers_a)
    assert res_a_get.status_code == 200
    a_data = res_a_get.json()["data"]
    assert a_data["sector_preferences"] == {"L2": 1.9}
    assert a_data["risk_tolerance"] == 0.9
    assert a_data["language"] == "en"


def test_preferences_admin_api_key(client: TestClient) -> None:
    """使用管理员 API Key 访问偏好接口正常工作。"""
    headers = {"X-API-Key": "test-admin-secret-api-key"}

    # 首次 GET
    res = client.get("/api/v1/user/preferences", headers=headers)
    assert res.status_code == 200
    assert res.json()["data"]["risk_tolerance"] == 0.5

    # PUT 更新
    put_res = client.put(
        "/api/v1/user/preferences",
        headers=headers,
        json={"risk_tolerance": 0.88, "theme": "light"},
    )
    assert put_res.status_code == 200
    assert put_res.json()["data"]["risk_tolerance"] == 0.88
    assert put_res.json()["data"]["theme"] == "light"

    # 再次 GET 确认
    get_res = client.get("/api/v1/user/preferences", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["data"]["risk_tolerance"] == 0.88
    assert get_res.json()["data"]["theme"] == "light"
