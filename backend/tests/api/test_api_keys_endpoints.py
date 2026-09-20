"""API integration tests for API Key management and authentication (W12-09, ROADMAP §25.3.3, §25.10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app
from app.repositories.user import UserRepository


@pytest.fixture(autouse=True)
def clean_db():
    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM users")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM blacklisted_jti")
        conn.execute("DELETE FROM sessions")
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM users")
        conn.commit()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    with TestClient(create_app()) as c:
        yield c


def test_api_keys_unauthenticated_and_anonymous(client: TestClient) -> None:
    """未认证请求与匿名 Token 访问 API Key 接口统一返回 401。"""
    # 1. 无凭据
    res = client.get("/api/v1/api-keys")
    assert res.status_code == 401
    res = client.post("/api/v1/api-keys", json={"name": "Test Key"})
    assert res.status_code == 401
    res = client.delete("/api/v1/api-keys/key_123")
    assert res.status_code == 401

    # 2. 匿名 Token (V2 HMAC)
    anon_res = client.post("/api/v1/auth/anonymous")
    assert anon_res.status_code == 200
    anon_token = anon_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {anon_token}"}

    res = client.get("/api/v1/api-keys", headers=headers)
    assert res.status_code == 401
    assert res.json()["error"]["code"] == "UNAUTHORIZED"

    res = client.post("/api/v1/api-keys", headers=headers, json={"name": "Test Key"})
    assert res.status_code == 401

    res = client.delete("/api/v1/api-keys/key_123", headers=headers)
    assert res.status_code == 401


def test_api_keys_crud_and_role_escalation_protection(client: TestClient) -> None:
    """验证 API Key 的 CRUD 流程与非管理员越权提权防护。"""
    # 1. 注册首个用户（自举为 admin）
    reg_admin = client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "Password123", "display_name": "Admin"},
    )
    assert reg_admin.status_code == 200

    # 2. 注册普通用户（默认 viewer）
    reg_viewer = client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@example.com", "password": "Password123", "display_name": "Viewer"},
    )
    assert reg_viewer.status_code == 200
    viewer_token = reg_viewer.json()["access_token"]
    viewer_headers = {"Authorization": f"Bearer {viewer_token}"}

    # 3. 越权提权防护：viewer 尝试创建 admin 或 analyst 角色的 Key 必须被 403 拦截
    res_escalate_admin = client.post(
        "/api/v1/api-keys",
        headers=viewer_headers,
        json={"name": "Escalate to Admin", "role": "admin"},
    )
    assert res_escalate_admin.status_code == 403
    assert res_escalate_admin.json()["error"]["code"] == "FORBIDDEN"

    res_escalate_analyst = client.post(
        "/api/v1/api-keys",
        headers=viewer_headers,
        json={"name": "Escalate to Analyst", "role": "analyst"},
    )
    assert res_escalate_analyst.status_code == 403

    # 4. viewer 创建自身角色 (viewer) 的 Key 成功
    create_res = client.post(
        "/api/v1/api-keys",
        headers=viewer_headers,
        json={"name": "Viewer Read Key", "expires_in_days": 30},
    )
    assert create_res.status_code == 200
    resp_data = create_res.json()["data"]
    raw_key = resp_data["raw_key"]
    key_info = resp_data["key"]

    assert raw_key.startswith("ak_")
    assert key_info["role"] == "viewer"
    assert key_info["name"] == "Viewer Read Key"
    assert key_info["expires_at"] is not None

    # 5. 列出 Key：已脱敏，不含 raw_key 与 key_hash
    list_res = client.get("/api/v1/api-keys", headers=viewer_headers)
    assert list_res.status_code == 200
    keys = list_res.json()["data"]
    assert len(keys) == 1
    assert keys[0]["id"] == key_info["id"]
    assert "raw_key" not in keys[0]
    assert "key_hash" not in keys[0]

    # 6. 撤销 Key
    del_res = client.delete(f"/api/v1/api-keys/{key_info['id']}", headers=viewer_headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["key_id"] == key_info["id"]

    # 列表不再包含（未传 include_revoked）
    list_res2 = client.get("/api/v1/api-keys", headers=viewer_headers)
    assert len(list_res2.json()["data"]) == 0

    # 传入 include_revoked=true 可以查出已撤销 Key
    list_res3 = client.get("/api/v1/api-keys?include_revoked=true", headers=viewer_headers)
    assert len(list_res3.json()["data"]) == 1
    assert list_res3.json()["data"][0]["is_revoked"] is True


def test_authenticate_with_dynamic_api_key(client: TestClient) -> None:
    """完整验证使用动态生成的 API Key 进行鉴权并执行受保护操作。"""
    # 注册用户并提升为 analyst
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "analyst@example.com", "password": "Password123", "display_name": "Analyst"},
    )
    user_id = reg.json()["user"]["id"]
    with get_connection() as conn:
        UserRepository(conn).update_role(user_id, "analyst")

    # 重新登录以获取包含 analyst role 的 JWT
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "analyst@example.com", "password": "Password123"},
    )
    jwt_token = login_res.json()["access_token"]
    jwt_headers = {"Authorization": f"Bearer {jwt_token}"}

    # 创建一个 analyst API Key
    create_res = client.post(
        "/api/v1/api-keys",
        headers=jwt_headers,
        json={"name": "Analyst Bot Key", "role": "analyst"},
    )
    assert create_res.status_code == 200
    raw_key = create_res.json()["data"]["raw_key"]
    key_id = create_res.json()["data"]["key"]["id"]

    # 1. 使用该 API Key（通过 Authorization: Bearer <raw_key>）访问受保护端点
    key_headers = {"Authorization": f"Bearer {raw_key}"}
    res_prefs = client.get("/api/v1/user/preferences", headers=key_headers)
    assert res_prefs.status_code == 200
    assert res_prefs.json()["ok"] is True

    # 2. analyst 角色尝试访问 admin-only 运维端点 (/run) 必须被 RBAC 403 拦截
    run_res = client.post("/api/v1/run", headers=key_headers, json={})
    assert run_res.status_code == 403
    assert run_res.json()["error"]["code"] == "FORBIDDEN"

    # 3. 验证数据库中该 key 的 last_used_at 已被更新
    key_list = client.get("/api/v1/api-keys", headers=jwt_headers).json()["data"]
    assert key_list[0]["last_used_at"] is not None

    # 4. 撤销该 Key
    del_res = client.delete(f"/api/v1/api-keys/{key_id}", headers=jwt_headers)
    assert del_res.status_code == 200

    # 5. 撤销后再使用该 Key 访问，必须返回 401 UNAUTHORIZED
    revoked_res = client.get("/api/v1/user/preferences", headers=key_headers)
    assert revoked_res.status_code == 401
    assert revoked_res.json()["error"]["code"] == "UNAUTHORIZED"


def test_api_key_multi_user_isolation(client: TestClient) -> None:
    """验证多用户之间 API Key 隔离性及管理员全局管理权限。"""
    # 注册用户 A (admin)
    res_a = client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "Password123", "display_name": "Admin"},
    )
    token_a = res_a.json()["access_token"]
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # 注册用户 B (viewer)
    res_b = client.post(
        "/api/v1/auth/register",
        json={"email": "bob@example.com", "password": "Password123", "display_name": "Bob"},
    )
    token_b = res_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # 用户 A 和 用户 B 分别创建 Key
    key_a = client.post("/api/v1/api-keys", headers=headers_a, json={"name": "Key A"}).json()["data"]["key"]
    key_b = client.post("/api/v1/api-keys", headers=headers_b, json={"name": "Key B"}).json()["data"]["key"]

    # 1. 用户 B 查自己的列表只能看到 Key B
    b_keys = client.get("/api/v1/api-keys", headers=headers_b).json()["data"]
    assert len(b_keys) == 1
    assert b_keys[0]["id"] == key_b["id"]

    # 2. 用户 B 尝试删除用户 A 的 Key，必须返回 404 (不确认资源存在性)
    del_cross = client.delete(f"/api/v1/api-keys/{key_a['id']}", headers=headers_b)
    assert del_cross.status_code == 404

    # 3. 用户 A (admin) 可以通过 ?all=true 查看所有用户的 Key
    all_keys = client.get("/api/v1/api-keys?all=true", headers=headers_a).json()["data"]
    assert len(all_keys) == 2

    # 4. 用户 A (admin) 可以撤销用户 B 的 Key
    del_admin = client.delete(f"/api/v1/api-keys/{key_b['id']}", headers=headers_a)
    assert del_admin.status_code == 200
