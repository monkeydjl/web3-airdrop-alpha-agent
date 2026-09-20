"""API integration tests for GDPR compliance endpoints (W12-11, ROADMAP §25.9, §25.10 / ADR-008 §6)."""

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
        conn.execute("DELETE FROM api_keys")
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM watchlist")
        conn.execute("DELETE FROM project_skips")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM projects WHERE id IN ('test_proj_1', 'test_proj_2')")
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
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM projects WHERE id IN ('test_proj_1', 'test_proj_2')")
        conn.commit()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-admin-secret-api-key")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    monkeypatch.setattr(settings, "enable_events_tracking", True)
    with TestClient(create_app()) as c:
        yield c


def test_gdpr_unauthenticated_and_anonymous(client: TestClient) -> None:
    """未认证请求与匿名 Token 访问 GDPR 接口统一返回 401。"""
    # 1. 无凭据
    res_get = client.get("/api/v1/user/data")
    assert res_get.status_code == 401, f"GET without auth expected 401, got {res_get.status_code}"

    res_del = client.delete("/api/v1/user/account")
    assert res_del.status_code == 401, f"DELETE without auth expected 401, got {res_del.status_code}"

    # 2. 匿名 Token (V2 HMAC)
    anon_res = client.post("/api/v1/auth/anonymous")
    assert anon_res.status_code == 200
    anon_token = anon_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {anon_token}"}

    res_get_anon = client.get("/api/v1/user/data", headers=headers)
    assert res_get_anon.status_code == 401
    assert res_get_anon.json()["error"]["code"] == "UNAUTHORIZED"

    res_del_anon = client.delete("/api/v1/user/account", headers=headers)
    assert res_del_anon.status_code == 401
    assert res_del_anon.json()["error"]["code"] == "UNAUTHORIZED"


def test_gdpr_data_export_endpoint(client: TestClient) -> None:
    """测试已认证用户导出个人数据完整流程。"""
    # 插入项目供关注和跳过
    with get_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO projects (id, name, score) VALUES ('test_proj_1', 'Test Project 1', 80)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO projects (id, name, score) VALUES ('test_proj_2', 'Test Project 2', 60)"
        )
        conn.commit()

    # 注册用户
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "Password123", "display_name": "Alice"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 设置偏好
    client.put(
        "/api/v1/user/preferences",
        headers=headers,
        json={"theme": "dark", "language": "zh", "risk_tolerance": 0.8},
    )

    # 提交一条反馈
    fb_res = client.post(
        "/api/v1/feedback",
        headers=headers,
        json={"project_id": "test_proj_1", "signal": "useful", "note": "Great"},
    )
    assert fb_res.status_code == 200

    # 上报一个行为事件
    ev_res = client.post(
        "/api/v1/events",
        headers=headers,
        json={"event_type": "click", "project_id": "test_proj_1", "detail": '{"button": "detail"}'},
    )
    assert ev_res.status_code == 200

    # 加关注
    wl_res = client.post(
        "/api/v1/watchlist/test_proj_1",
        headers=headers,
        json={"notes": "Must watch"},
    )
    assert wl_res.status_code == 200

    # 标记跳过
    skip_res = client.post(
        "/api/v1/projects/test_proj_2/skip",
        headers=headers,
        json={"reason": "Scam suspect"},
    )
    assert skip_res.status_code == 200

    # 导出个人数据
    res = client.get("/api/v1/user/data", headers=headers)
    assert res.status_code == 200
    data = res.json()["data"]

    # 验证基础信息
    assert data["user"]["email"] == "alice@example.com"
    assert data["user"]["display_name"] == "Alice"
    assert "password_hash" not in data["user"]

    # 验证偏好
    assert data["preferences"]["theme"] == "dark"
    assert data["preferences"]["language"] == "zh"
    assert data["preferences"]["risk_tolerance"] == 0.8

    # 验证业务数据存在
    assert len(data["feedback"]) == 1
    assert data["feedback"][0]["project_id"] == "test_proj_1"

    assert len(data["events"]) == 1
    assert data["events"][0]["event_type"] == "click"

    assert len(data["watchlist"]) == 1
    assert data["watchlist"][0]["project_id"] == "test_proj_1"

    assert len(data["project_skips"]) == 1
    assert data["project_skips"][0]["project_id"] == "test_proj_2"


def test_gdpr_account_deletion_flow(client: TestClient) -> None:
    """测试账户注销：反馈去标识化、事件删除、Token 吊销与邮箱重新注册。"""
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "charlie@example.com", "password": "Password123", "display_name": "Charlie"},
    )
    assert reg.status_code == 200
    token = reg.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 写入反馈与事件
    fb_res = client.post(
        "/api/v1/feedback",
        headers=headers,
        json={"project_id": "p_charlie", "signal": "useless", "note": "Bad"},
    )
    assert fb_res.status_code == 200

    ev_res = client.post(
        "/api/v1/events",
        headers=headers,
        json={"event_type": "view", "project_id": "p_charlie"},
    )
    assert ev_res.status_code == 200

    # 注销账户
    del_res = client.delete("/api/v1/user/account", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["data"]["status"] == "deleted"

    # 原 Token 再次请求应返回 401（已进黑名单 / 用户已不存在）
    me_res = client.get("/api/v1/auth/me", headers=headers)
    assert me_res.status_code == 401

    export_res = client.get("/api/v1/user/data", headers=headers)
    assert export_res.status_code == 401

    # 检查数据库：feedback 样本保留但 user_id 为 NULL
    with get_connection() as conn:
        fb_row = conn.execute("SELECT user_id, signal FROM feedback WHERE project_id = 'p_charlie'").fetchone()
        assert fb_row is not None
        assert fb_row[0] is None  # user_id is NULL
        assert fb_row[1] == "useless"

        # events 彻底物理删除
        events_cnt = conn.execute("SELECT COUNT(*) FROM events WHERE project_id = 'p_charlie'").fetchone()[0]
        assert events_cnt == 0

    # 同一邮箱可立即重新注册新账户
    re_reg = client.post(
        "/api/v1/auth/register",
        json={"email": "charlie@example.com", "password": "NewPassword456", "display_name": "Charlie V2"},
    )
    assert re_reg.status_code == 200
    new_token = re_reg.json()["access_token"]
    assert new_token != token
