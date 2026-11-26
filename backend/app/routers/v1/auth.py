"""Authentication & User Session Endpoints (V2 & V3, ADR-008).

提供匿名 token、用户注册、登录、刷新、登出、全设备登出与当前用户信息接口。

Reference:
- ADR-008-user-system.md §V2 匿名 token & §V3 JWT / sessions / 吊销
- ENGINEERING_ROADMAP.md §25.3.3 & §25.10
"""

from __future__ import annotations

import hmac
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
    extract_renewable_anonymous_user_id,
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
from app.db import connection_scope
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


def _first_user_role(bootstrap_token: str | None) -> str | None:
    """首位注册用户的角色判定（防抢注，2026-11-13 审查 H-2）。

    `/auth/register` 在 PUBLIC_PREFIXES 上 —— 此前"首位注册即 admin"等于
    公网新部署时攻击者抢注即得永久管理员。规则：

    - 配置了 `REGISTRATION_BOOTSTRAP_TOKEN` → 必须携带正确 token 才得 admin
      （常量时间比较；配置即生效，不分环境）；
    - 生产环境未配置 → 降级 viewer 并告警（运维应配置 token 后再注册首位账号）；
    - 开发/测试未配置 → 保持原自举行为（admin），DX 不变。

    Returns:
        "admin" / "viewer"；None 表示校验失败（调用方拒绝创建用户，
        自举名额不被消费）。
    """
    expected = settings.registration_bootstrap_token.strip()
    if expected:
        provided = (bootstrap_token or "").strip()
        if not hmac.compare_digest(provided, expected):
            return None
        return "admin"
    if settings.is_production:
        logger.warning(
            "auth.first_user_bootstrap_degraded",
            hint="Set REGISTRATION_BOOTSTRAP_TOKEN and register with it to create the admin",
        )
        return "viewer"
    return "admin"


# ═══════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════


class AnonymousTokenRequest(BaseModel):
    """匿名 token 签发/续期请求（可选携带旧签名 token 以续用同一 anon-<id>）。"""

    previous_token: str | None = Field(
        default=None,
        max_length=1024,
        description="上次由服务端签发的匿名 token（过期后验签通过可原样续用 user_id，防止个人数据断链）",
    )


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

    email: str = Field(..., max_length=256, description="用户邮箱")
    password: str = Field(..., max_length=1024, description="密码（长度≥8且≤72字节，包含大小写字母+数字）")
    display_name: str | None = Field(default=None, max_length=128, description="显示名称（可选）")
    bootstrap_token: str | None = Field(
        default=None,
        max_length=512,
        description="首位 admin 自举令牌（仅当服务端配置了 REGISTRATION_BOOTSTRAP_TOKEN 时需要）",
    )


class LoginRequest(BaseModel):
    """用户登录请求。"""

    email: str = Field(..., max_length=256, description="用户邮箱")
    password: str = Field(..., max_length=1024, description="密码")


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
    description="签发一个匿名 Bearer token，用于访问受保护 API 端点。无需认证；携带已过期的合法签名 token 时续用原 user_id。",
)
def issue_anonymous(body: AnonymousTokenRequest | None = None) -> AnonymousTokenResponse:
    """签发或续期匿名 token（V2 兼容）。"""
    preserved_uid = extract_renewable_anonymous_user_id(body.previous_token if body else None)
    token = issue_anonymous_token(user_id=preserved_uid)

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
    description=(
        "创建新用户账户并返回 JWT Access Token 与 Refresh Token。首位用户默认自举为 admin；"
        "生产环境或配置了 REGISTRATION_BOOTSTRAP_TOKEN 的部署需要携带正确的 bootstrap_token "
        "才能获得 admin（防公网抢注，2026-11-13）。ALLOW_REGISTRATION=false 时关闭注册。"
    ),
)
def register(body: RegisterRequest) -> Any:
    """用户注册端点。"""
    if not settings.allow_registration:
        return _error(403, "REGISTRATION_DISABLED", "Registration is disabled on this deployment")

    email = body.email.strip()
    if not _EMAIL_PATTERN.match(email):
        return _error(400, "INVALID_EMAIL", "Invalid email address format")

    valid_pwd, pwd_err = validate_password_strength(body.password)
    if not valid_pwd:
        return _error(400, "WEAK_PASSWORD", pwd_err)

    with connection_scope() as conn:
        user_repo = UserRepository(conn)
        if user_repo.get_by_email(email) is not None:
            return _error(400, "EMAIL_ALREADY_REGISTERED", "Email is already registered")

        user_count = user_repo.count_users()
        if user_count == 0:
            role = _first_user_role(body.bootstrap_token)
            if role is None:
                # fail-closed：token 不对就不建用户，自举名额不被消费
                return _error(403, "BOOTSTRAP_TOKEN_REQUIRED", "Bootstrap token missing or incorrect")
        else:
            role = "viewer"

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


def _mask_email(email: str) -> str:
    """日志用邮箱脱敏：保留前两字符与域名，其余以 *** 代替（PII 不落日志管道）。"""
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    prefix = local[:2] if local else ""
    return f"{prefix}***@{domain}"


_dummy_hash_cache: str | None = None


def _dummy_password_hash() -> str:
    """惰性生成一次哑 bcrypt 哈希，供"未知邮箱"的登录路径做**时序均衡**。

    未知邮箱直接 return 会跳过 bcrypt（约 200ms 级差异）——响应时间差可被
    用于枚举已注册邮箱（2026-11-13 审查 L-2）。两条失败路径都必须走一次
    验证，结果一律丢弃。
    """
    global _dummy_hash_cache
    if _dummy_hash_cache is None:
        _dummy_hash_cache = hash_password("timing-equalization-dummy-" + uuid.uuid4().hex)
    return _dummy_hash_cache


@router.post(
    "/auth/login",
    response_model=AuthTokenResponse,
    summary="用户登录",
    description="凭邮箱与密码登录，验证成功后返回 JWT Access Token 与 Refresh Token，并创建持久化 Session。",
)
def login(body: LoginRequest) -> Any:
    """用户登录端点。"""
    email = body.email.strip()
    with connection_scope() as conn:
        user_repo = UserRepository(conn)
        user = user_repo.get_by_email(email)

        if not user or not user.get("is_active"):
            # 时序均衡（2026-11-13 审查 L-2）：未命中也走一次 bcrypt，让
            # "邮箱不存在"与"密码错误"的响应时间同型，邮箱枚举失去时钟。
            verify_password(body.password, _dummy_password_hash())
            logger.warning("auth.login_failed", email=_mask_email(email), reason="not_found_or_inactive")
            return _error(401, "INVALID_CREDENTIALS", "Invalid email or password")

        if not verify_password(body.password, str(user["password_hash"])):
            logger.warning("auth.login_failed", email=_mask_email(email), reason="bad_password")
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

    with connection_scope() as conn:
        session_repo = SessionRepository(conn)
        session = session_repo.get_by_token_hash(refresh_token_hash)

        if not session or session.get("revoked", 0) == 1:
            return _error(401, "SESSION_REVOKED", "Session has been revoked or does not exist")

        user_repo = UserRepository(conn)
        user = user_repo.get_by_id(payload["sub"])
        if not user or not user.get("is_active"):
            return _error(401, "USER_INACTIVE", "User account is inactive or deleted")

        access_token, _access_jti, expires_in = issue_access_token(user["id"], user["role"])
        refresh_token, _refresh_jti, refresh_expires_in = issue_refresh_token(user["id"])

        # 轮换（2026-11-13 审查 L-3）：旧 session 即刻吊销、新 refresh 换新
        # session —— 被偷走的旧 token 在受害者下一次刷新时即失效，而不是
        # 继续有效 7 天。客户端按标准流程保存响应里的新 refresh token。
        session_repo.revoke_session(str(session["id"]))
        session_repo.create_session(
            session_id=f"ses_{uuid.uuid4().hex[:12]}",
            user_id=user["id"],
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=datetime.fromtimestamp(time.time() + refresh_expires_in, tz=UTC),
        )

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
        refresh_token=refresh_token,
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
    user_id = str(current_user.get("user_id") or "")
    role = current_user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or user_id.startswith("anon-"):
        return _error(401, "UNAUTHORIZED", "Authentication required to logout")

    jwt_jti = current_user.get("jwt_jti")
    if jwt_jti:
        blacklist_token_jti(jwt_jti)

    if body and body.refresh_token:
        with connection_scope() as conn:
            session_repo = SessionRepository(conn)
            session_repo.revoke_by_token_hash_for_user(hash_refresh_token(body.refresh_token), user_id)

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
    user_id = str(current_user.get("user_id") or "")
    role = current_user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or user_id.startswith("anon-"):
        return _error(401, "UNAUTHORIZED", "Authentication required")

    jwt_jti = current_user.get("jwt_jti")
    if jwt_jti:
        blacklist_token_jti(jwt_jti)

    with connection_scope() as conn:
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

    with connection_scope() as conn:
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
