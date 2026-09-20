import pytest
from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_auth_tables():
    """每次测试前后清理 users, sessions, blacklisted_jti 表。"""
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
    """创建测试客户端并自动初始化 DB。"""
    app = create_app()
    return TestClient(app)


def test_register_and_login_flow(client: TestClient) -> None:
    """测试注册与登录全链路，包含首用户 admin 自举与次用户 viewer 默认角色。"""
    # 1. 注册首位用户 -> 应自举为 admin
    reg_payload1 = {
        "email": "alice@example.com",
        "password": "Password123",
        "display_name": "Alice Admin",
    }
    r1 = client.post("/api/v1/auth/register", json=reg_payload1)
    assert r1.status_code == 200, r1.text
    data1 = r1.json()
    assert data1["access_token"]
    assert data1["refresh_token"]
    assert data1["token_type"] == "Bearer"
    assert data1["user"]["email"] == "alice@example.com"
    assert data1["user"]["role"] == "admin"

    # 2. 注册第二位用户 -> 默认 viewer
    reg_payload2 = {
        "email": "bob@example.com",
        "password": "Password456",
        "display_name": "Bob Viewer",
    }
    r2 = client.post("/api/v1/auth/register", json=reg_payload2)
    assert r2.status_code == 200, r2.text
    data2 = r2.json()
    assert data2["user"]["email"] == "bob@example.com"
    assert data2["user"]["role"] == "viewer"

    # 3. 重复邮箱注册拒绝
    r_dup = client.post("/api/v1/auth/register", json=reg_payload1)
    assert r_dup.status_code == 400
    assert r_dup.json()["error"]["code"] == "EMAIL_ALREADY_REGISTERED"

    # 4. 弱密码注册拒绝
    r_weak = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "123"},
    )
    assert r_weak.status_code == 400
    assert r_weak.json()["error"]["code"] == "WEAK_PASSWORD"

    # 5. 登录 Alice
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "Password123"},
    )
    assert login_resp.status_code == 200
    login_data = login_resp.json()
    assert login_data["access_token"]
    assert login_data["user"]["role"] == "admin"

    # 6. 错误密码登录拒绝
    login_fail = client.post(
        "/api/v1/auth/login",
        json={"email": "alice@example.com", "password": "WrongPassword"},
    )
    assert login_fail.status_code == 401
    assert login_fail.json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_auth_me_and_token_refresh(client: TestClient) -> None:
    """测试 /auth/me 获取当前身份及 /auth/refresh 刷新 access token。"""
    # 注册用户
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "carol@example.com", "password": "Password789", "display_name": "Carol"},
    )
    assert reg_resp.status_code == 200
    tokens = reg_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 1. 访问 /auth/me（携带 access token）
    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_resp.status_code == 200
    me_data = me_resp.json()
    assert me_data["email"] == "carol@example.com"
    assert me_data["display_name"] == "Carol"

    # 2. 未携带 token 访问 /auth/me -> 401
    me_unauth = client.get("/api/v1/auth/me")
    assert me_unauth.status_code == 401

    # 3. 刷新 token
    refresh_resp = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert refresh_resp.status_code == 200
    new_tokens = refresh_resp.json()
    new_access_token = new_tokens["access_token"]
    assert new_access_token

    # 4. 新 token 访问 /auth/me
    me_new = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_access_token}"},
    )
    assert me_new.status_code == 200


def test_logout_and_revocation(client: TestClient) -> None:
    """测试登出、JTI 黑名单吊销以及全设备登出。"""
    # 注册用户
    reg_resp = client.post(
        "/api/v1/auth/register",
        json={"email": "dave@example.com", "password": "Password123"},
    )
    tokens = reg_resp.json()
    access_token = tokens["access_token"]
    refresh_token = tokens["refresh_token"]

    # 1. 登出当前设备
    logout_resp = client.post(
        "/api/v1/auth/logout",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"refresh_token": refresh_token},
    )
    assert logout_resp.status_code == 200
    assert logout_resp.json()["ok"] is True

    # 2. 已登出的 access_token 再次访问应被拒绝 (401)
    me_after = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_after.status_code == 401

    # 3. 已撤销的 refresh_token 刷新应被拒绝 (401)
    ref_after = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    assert ref_after.status_code == 401

    # 4. 重新登录后测试全设备登出
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "dave@example.com", "password": "Password123"},
    )
    assert login_resp.status_code == 200
    new_access = login_resp.json()["access_token"]

    logout_all_resp = client.post(
        "/api/v1/auth/logout/all",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert logout_all_resp.status_code == 200
    assert logout_all_resp.json()["ok"] is True


def test_anonymous_endpoint(client: TestClient) -> None:
    """测试匿名 token 签发端点保持正常可用。"""
    resp = client.post("/api/v1/auth/anonymous")
    assert resp.status_code == 200
    data = resp.json()
    assert data["access_token"]
    assert data["token_type"] == "Bearer"
    assert data["user_id"].startswith("anon-")
