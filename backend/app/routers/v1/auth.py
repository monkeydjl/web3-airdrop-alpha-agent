"""Authentication & User Session Endpoints (V2 & V3, ADR-008).

提供匿名 token、用户注册、登录、刷新、登出、全设备登出与当前用户信息接口。

Reference:
- ADR-008-user-system.md §V2 匿名 token & §V3 JWT / sessions / 吊销
- ENGINEERING_ROADMAP.md §25.3.3 & §25.10
"""

from __future__ import annotations

import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.auth import (
    blacklist_token_jti,
    decode_and_verify_jwt,
    get_current_user,
    hash_password,
    hash_refresh_token,
    issue_access_token,
    issue_anonymous_token,
    issue_refresh_token,
    validate_password_strength,
    verify_password,
    verify_token,
)
from app.config import settings
from app.db import get_connection
from app.repositories.user import SessionRepository, UserRepository

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])

_EMAIL_PATTERN = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    """返回标准 JSON 错误响应。"""
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


# ═══════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════


class AnonymousTokenResponse(BaseModel):
    """匿名 token 签发响应。"""

    access_token: str = Field(..., description="匿名 Bearer token")
    token_type: str = Field(default="Bearer", description="token 类型")
    expires_in: int = Field(..., description="有效期（秒）")
    user_id: str = Field(..., description="用户标识")


class UserResponse(BaseModel):
    """用户信息响应。"""

    id: str = Field(..., description="用户唯一标识 (UUID)")
    email: str = Field(..., description="用户邮箱")
    display_name: str | None = Field(default=None, description="显示名称")
    role: str = Field(..., description="用户角色 (admin|analyst|viewer)")
    is_active: bool = Field(default=True, description="是否处于活跃状态")
    created_at: str | None = Field(default=None, description="注册时间")


class AuthTokenResponse(BaseModel):
    """JWT 认证响应（登录/注册/刷新）。"""

    access_token: str = Field(..., description="JWT Access Token")
    refresh_token: str = Field(..., description="JWT Refresh Token")
    token_type: str = Field(default="Bearer", description="token 类型")
    expires_in: int = Field(..., description="Access Token 有效期（秒）")
    user: UserResponse = Field(..., description="用户信息")


class RegisterRequest(BaseModel):
    """用户注册请求。"""

    email: str = Field(..., description="用户邮箱")
    password: str = Field(..., description="密码（长度≥8，包含大小写字母+数字）")
    display_name: str | None = Field(default=None, description="显示名称（可选）")


class LoginRequest(BaseModel):
    """用户登录请求。"""

    email: str = Field(..., description="用户邮箱")
    password: str = Field(..., description="密码")


class RefreshTokenRequest(BaseModel):
    """刷新 Token 请求。"""

    refresh_token: str = Field(..., description="JWT Refresh Token")


class LogoutRequest(BaseModel):
    """登出请求（可选携带 refresh_token 以同步标记会话撤销）。"""

    refresh_token: str | None = Field(default=None, description="需要撤销的 Refresh Token（可选）")


class MessageResponse(BaseModel):
    """通用消息响应。"""

    ok: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/auth/anonymous",
    response_model=AnonymousTokenResponse,
    summary="签发匿名 token",
    description="签发一个匿名 Bearer token，用于访问受保护 API 端点。无需认证。",
)
def issue_anonymous() -> AnonymousTokenResponse:
    """签发匿名 token（V2 兼容）。"""
    token = issue_anonymous_token()

    payload = verify_token(token)
    actual_user_id = payload["user_id"] if payload else "anonymous"

    expires_in = settings.auth_token_ttl_hours * 3600

    logger.info(
        "auth.anonymous_token_issued",
        user_id=actual_user_id,
        expires_in=expires_in,
    )

    return AnonymousTokenResponse(
        access_token=token,
        token_type="Bearer",  # noqa: S106
        expires_in=expires_in,
        user_id=actual_user_id,
    )


@router.post(
    "/auth/register",
    response_model=AuthTokenResponse,
    summary="用户注册",
    description="创建新用户账户并返回 JWT Access Token 与 Refresh Token。首位注册用户自举为 admin，后续用户为 viewer。",
)
def register(body: RegisterRequest) -> Any:
    """用户注册端点。"""
    email = body.email.strip()
    if not _EMAIL_PATTERN.match(email):
        return _error(400, "INVALID_EMAIL", "Invalid email address format")

    valid_pwd, pwd_err = validate_password_strength(body.password)
    if not valid_pwd:
        return _error(400, "WEAK_PASSWORD", pwd_err)

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        if user_repo.get_by_email(email) is not None:
            return _error(400, "EMAIL_ALREADY_REGISTERED", "Email is already registered")

        user_count = user_repo.count_users()
        role = "admin" if user_count == 0 else "viewer"

        user_id = f"usr_{uuid.uuid4().hex[:12]}"
        password_hash = hash_password(body.password)

        created_user = user_repo.create_user(
            user_id=user_id,
            email=email,
            password_hash=password_hash,
            display_name=body.display_name.strip() if body.display_name else None,
            role=role,
        )

        access_token, _access_jti, expires_in = issue_access_token(user_id, role)
        refresh_token, _refresh_jti, refresh_expires_in = issue_refresh_token(user_id)

        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        refresh_token_hash = hash_refresh_token(refresh_token)
        expires_at = datetime.fromtimestamp(time.time() + refresh_expires_in, tz=UTC)

        session_repo = SessionRepository(conn)
        session_repo.create_session(
            session_id=session_id,
            user_id=user_id,
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
        )

    logger.info("auth.user_registered", user_id=user_id, email=email, role=role)

    user_resp = UserResponse(
        id=created_user["id"],
        email=created_user["email"],
        display_name=created_user.get("display_name"),
        role=created_user["role"],
        is_active=bool(created_user["is_active"]),
        created_at=str(created_user["created_at"]) if created_user.get("created_at") else None,
    )

    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",  # noqa: S106
        expires_in=expires_in,
        user=user_resp,
    )


@router.post(
    "/auth/login",
    response_model=AuthTokenResponse,
    summary="用户登录",
    description="凭邮箱与密码登录，验证成功后返回 JWT Access Token 与 Refresh Token，并创建持久化 Session。",
)
def login(body: LoginRequest) -> Any:
    """用户登录端点。"""
    email = body.email.strip()
    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user = user_repo.get_by_email(email)

        if not user or not user.get("is_active"):
            logger.warning("auth.login_failed", email=email, reason="not_found_or_inactive")
            return _error(401, "INVALID_CREDENTIALS", "Invalid email or password")

        if not verify_password(body.password, str(user["password_hash"])):
            logger.warning("auth.login_failed", email=email, reason="bad_password")
            return _error(401, "INVALID_CREDENTIALS", "Invalid email or password")

        user_repo.update_last_login(user["id"])

        access_token, _access_jti, expires_in = issue_access_token(user["id"], user["role"])
        refresh_token, _refresh_jti, refresh_expires_in = issue_refresh_token(user["id"])

        session_id = f"ses_{uuid.uuid4().hex[:12]}"
        refresh_token_hash = hash_refresh_token(refresh_token)
        expires_at = datetime.fromtimestamp(time.time() + refresh_expires_in, tz=UTC)

        session_repo = SessionRepository(conn)
        session_repo.create_session(
            session_id=session_id,
            user_id=user["id"],
            refresh_token_hash=refresh_token_hash,
            expires_at=expires_at,
        )

    logger.info("auth.user_logged_in", user_id=user["id"], role=user["role"])

    user_resp = UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user.get("display_name"),
        role=user["role"],
        is_active=bool(user["is_active"]),
        created_at=str(user["created_at"]) if user.get("created_at") else None,
    )

    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer",  # noqa: S106
        expires_in=expires_in,
        user=user_resp,
    )


@router.post(
    "/auth/refresh",
    response_model=AuthTokenResponse,
    summary="刷新 Access Token",
    description="校验 Refresh Token 及持久化 session 状态，验证通过后签发新的 Access Token。",
)
def refresh_token_endpoint(body: RefreshTokenRequest) -> Any:
    """刷新 Access Token 端点。"""
    payload = decode_and_verify_jwt(body.refresh_token, expected_type="refresh")
    if not payload:
        return _error(401, "INVALID_REFRESH_TOKEN", "Invalid or expired refresh token")

    refresh_token_hash = hash_refresh_token(body.refresh_token)

    with get_connection() as conn:
        session_repo = SessionRepository(conn)
        session = session_repo.get_by_token_hash(refresh_token_hash)

        if not session or session.get("revoked", 0) == 1:
            return _error(401, "SESSION_REVOKED", "Session has been revoked or does not exist")

        user_repo = UserRepository(conn)
        user = user_repo.get_by_id(payload["sub"])
        if not user or not user.get("is_active"):
            return _error(401, "USER_INACTIVE", "User account is inactive or deleted")

        access_token, _access_jti, expires_in = issue_access_token(user["id"], user["role"])

    logger.info("auth.token_refreshed", user_id=user["id"])

    user_resp = UserResponse(
        id=user["id"],
        email=user["email"],
        display_name=user.get("display_name"),
        role=user["role"],
        is_active=bool(user["is_active"]),
        created_at=str(user["created_at"]) if user.get("created_at") else None,
    )

    return AuthTokenResponse(
        access_token=access_token,
        refresh_token=body.refresh_token,
        token_type="Bearer",  # noqa: S106
        expires_in=expires_in,
        user=user_resp,
    )


@router.post(
    "/auth/logout",
    response_model=MessageResponse,
    summary="登出当前会话",
    description="吊销当前 JWT Access Token（记入 JTI 黑名单）并撤销对应 Session。",
)
def logout(request: Request, body: LogoutRequest | None = None) -> Any:
    """登出当前会话端点。"""
    current_user = get_current_user(request)
    user_id = current_user.get("user_id")

    if not user_id or user_id == "anonymous":
        return _error(401, "UNAUTHORIZED", "Authentication required to logout")

    jwt_jti = current_user.get("jwt_jti")
    if jwt_jti:
        blacklist_token_jti(jwt_jti)

    if body and body.refresh_token:
        with get_connection() as conn:
            session_repo = SessionRepository(conn)
            session_repo.revoke_by_token_hash(hash_refresh_token(body.refresh_token))

    logger.info("auth.user_logged_out", user_id=user_id)
    return MessageResponse(ok=True, data={"message": "Logged out successfully"})


@router.post(
    "/auth/logout/all",
    response_model=MessageResponse,
    summary="全设备登出",
    description="吊销当前 Access Token 并撤销该用户在所有设备上的持久化 Sessions。",
)
def logout_all(request: Request) -> Any:
    """全设备登出端点。"""
    current_user = get_current_user(request)
    user_id = current_user.get("user_id")

    if not user_id or user_id == "anonymous":
        return _error(401, "UNAUTHORIZED", "Authentication required")

    jwt_jti = current_user.get("jwt_jti")
    if jwt_jti:
        blacklist_token_jti(jwt_jti)

    with get_connection() as conn:
        session_repo = SessionRepository(conn)
        revoked_count = session_repo.revoke_all_user_sessions(user_id)

    logger.info("auth.all_sessions_revoked", user_id=user_id, count=revoked_count)
    return MessageResponse(ok=True, data={"message": "All sessions revoked", "revoked_sessions": revoked_count})


@router.get(
    "/auth/me",
    response_model=UserResponse,
    summary="获取当前用户信息",
    description="返回当前已认证用户的基本信息与角色。",
)
def get_me(request: Request) -> Any:
    """获取当前已登录用户信息。"""
    current_user = get_current_user(request)
    user_id = current_user.get("user_id")
    role = current_user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or user_id.startswith("anon-"):
        return _error(401, "UNAUTHORIZED", "Authentication required")

    if user_id == "admin":
        return UserResponse(
            id="admin",
            email="admin@local",
            display_name="Administrator",
            role="admin",
            is_active=True,
            created_at=None,
        )

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user = user_repo.get_by_id(user_id)
        if not user:
            return _error(404, "USER_NOT_FOUND", "User not found")

        return UserResponse(
            id=user["id"],
            email=user["email"],
            display_name=user.get("display_name"),
            role=user["role"],
            is_active=bool(user["is_active"]),
            created_at=str(user["created_at"]) if user.get("created_at") else None,
        )
