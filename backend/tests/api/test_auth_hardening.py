"""认证端点安全加固回归（2026-11-13 审查 L-2 / L-3 / L-8 / L-9）。

- L-2 登录时序差：未知邮箱直接 return，跳过 bcrypt —— 响应时间差让
  攻击者可以枚举已注册邮箱。契约：未知邮箱也执行一次 bcrypt 验证
  （哑哈希），两条路径耗时同型。
- L-8 登录失败日志记录明文邮箱（PII 落日志管道）。契约：login_failed
  事件的 email 字段必须脱敏。
- L-9 /notify/test 把异常原文回显进响应 detail（可能带通道 URL/密钥）。
  契约：响应只给通用文案，细节只进日志。
- L-3 refresh token 不轮换：刷新后旧 refresh token 仍有效至 7 天 ——
  被偷走的 token 无法被受害者的正常使用吊销。契约：刷新即轮换，
  旧 token 在下一次刷新时 SESSION_REVOKED。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from structlog.testing import capture_logs

from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_auth_tables():
    """auth 状态跨测试持久（默认库）——每个用例前后清空 users/sessions/jti。"""
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


def _register(client: TestClient, email: str = "hardening@example.com") -> dict:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def _login(client: TestClient, email: str, password: str) -> dict:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password}).json()


# ── L-2 登录时序均衡 ────────────────────────────


def test_unknown_email_still_runs_bcrypt(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import app.routers.v1.auth as auth_router

    counter = {"n": 0}
    real_verify = auth_router.verify_password

    def counting_verify(password: str, hashed: str) -> bool:
        counter["n"] += 1
        return real_verify(password, hashed)

    monkeypatch.setattr(auth_router, "verify_password", counting_verify)

    _register(client, email="known@example.com")

    counter["n"] = 0
    # 已知邮箱 + 错密码：1 次 bcrypt
    _login(client, "known@example.com", "WrongPassword1")
    assert counter["n"] == 1

    # 未知邮箱：也必须恰好 1 次（哑哈希），否则时序差暴露"邮箱是否存在"
    counter["n"] = 0
    _login(client, "unknown@example.com", "WrongPassword1")
    assert counter["n"] == 1, f"未知邮箱登录执行了 {counter['n']} 次 bcrypt —— 响应时序可被用于枚举注册邮箱"


def test_login_failure_response_does_not_confirm_email_existence(
    client: TestClient,
) -> None:
    """两条失败路径的错误文案与状态码一致（本就如此），时序由上一条钉住。"""
    _register(client, email="known@example.com")
    bad_known = _login(client, "known@example.com", "WrongPassword1")
    bad_unknown = _login(client, "unknown@example.com", "WrongPassword1")
    assert bad_known == bad_unknown


# ── L-8 日志邮箱脱敏 ────────────────────────────


def test_login_failure_logs_mask_email(client: TestClient) -> None:
    _register(client, email="pii@example.com")

    with capture_logs() as logs:
        client.post("/api/v1/auth/login", json={"email": "pii@example.com", "password": "WrongPassword1"})

    events = [e for e in logs if e.get("event") == "auth.login_failed"]
    assert events, "没有捕获到登录失败日志 —— capture 口径失效，本测试空转"
    for e in events:
        email_field = str(e.get("email", ""))
        assert email_field != "pii@example.com", f"登录失败日志泄漏明文邮箱：{email_field}"


def test_mask_email_helper() -> None:
    import app.routers.v1.auth as auth_router

    assert auth_router._mask_email("pii@example.com") == "pi***@example.com"
    assert "pii@example.com" not in auth_router._mask_email("pii@example.com")
    assert auth_router._mask_email("x@y.com").startswith("x*")


# ── L-9 /notify/test 错误回显 ───────────────────


def test_notify_test_error_is_generic(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers.v1 import notify as notify_router

    class _BoomSender:
        channel = "telegram"

        async def send(self, title: str, body: str) -> None:
            raise RuntimeError("WEBHOOK-SECRET https://hooks.example.com/t/SECRET")

    monkeypatch.setattr(notify_router, "get_sender", lambda: _BoomSender())

    response = client.post("/api/v1/notify/test")
    assert response.status_code == 502
    assert "WEBHOOK-SECRET" not in response.text, f"异常原文（含通道 URL/密钥）被回显进响应：{response.text}"


# ── L-3 refresh token 轮换 ──────────────────────


def test_refresh_rotates_the_refresh_token(client: TestClient) -> None:
    tokens = _register(client, email="rotate@example.com")
    old_refresh = tokens["refresh_token"]

    first = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert first.status_code == 200
    new_refresh = first.json()["refresh_token"]
    assert new_refresh != old_refresh, "刷新后返回的还是旧 refresh token —— 没有轮换"

    # 旧 token 立即失效（被偷走的 token 在受害者下一次刷新时即被吊销）
    replay = client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401
    assert replay.json()["error"]["code"] == "SESSION_REVOKED"

    # 新 token 仍可继续刷新
    second = client.post("/api/v1/auth/refresh", json={"refresh_token": new_refresh})
    assert second.status_code == 200


# ── L-5 422 校验错误脱敏 ────────────────────────


def test_validation_errors_do_not_echo_input_or_internals(client: TestClient) -> None:
    """pydantic 的 errors() 带 `input`（原样回显用户输入）与 `ctx`/`url`
    （内部实现细节）——响应只保留 loc/type/msg（2026-11-13 审查 L-5）。"""
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "x@example.com", "password": "PASSWORD-SENTINEL-123", "display_name": 12345},
    )
    assert response.status_code == 422
    body = response.text
    assert "PASSWORD-SENTINEL-123" not in body, "422 响应回显了用户输入原文"
    assert '"input"' not in body and '"ctx"' not in body and '"url"' not in body
    details = response.json()["error"]["details"]
    assert details and all(set(d) <= {"loc", "type", "msg"} for d in details)
