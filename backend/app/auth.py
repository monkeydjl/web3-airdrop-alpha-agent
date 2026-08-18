"""API Key + Anonymous Token authentication (V2, ADR-008).

双令牌鉴权体系：
1. 管理员 API Key（settings.api_key）：完整权限，通过 X-API-Key 或 Bearer header
2. 匿名 token（HMAC-SHA256 签名）：受限权限，通过 Bearer header

匿名 token 格式（无 JWT 依赖，纯 HMAC）：
    base64url(payload_json) + "." + base64url(hmac_sha256(payload, secret))

payload: {"user_id": "anon-<uuid>", "role": "anonymous", "exp": <unix_ts>}

受保护端点（需要管理员权限）：
    POST /api/v1/run, POST /api/v1/re-score, DELETE 类操作

匿名用户允许：GET /projects, GET /discoveries, POST /feedback, GET /watchlist 等

Reference:
- ADR-008-user-system.md §V2 匿名 token
- ENGINEERING_ROADMAP.md §9
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import uuid
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import settings

logger = structlog.get_logger(__name__)

# Paths that stay open even with API key enabled
PUBLIC_PREFIXES = (
    "/health",
    "/metrics",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/version",
    "/api/v1/webhook",
    "/api/v1/auth/anonymous",  # 匿名 token 签发端点
)

# 需要管理员权限的端点（匿名 token 不可访问）
ADMIN_ONLY_PREFIXES = (
    "/api/v1/run",
    "/api/v1/re-score",
    "/api/v1/quarantine",
    "/api/v1/export",
    "/api/v1/import",
)


# ═══════════════════════════════════════════════════════════════
# Token 签发/校验
# ═══════════════════════════════════════════════════════════════


def _get_secret() -> bytes:
    """获取签名密钥，空时随机生成（仅 MVP 单进程）。"""
    secret = settings.auth_token_secret
    if not secret:
        # 随机生成（进程级缓存，重启后旧 token 失效）
        if not hasattr(_get_secret, "_cached"):
            _get_secret._cached = os.urandom(32)
        return _get_secret._cached  # type: ignore[attr-defined]
    return secret.encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    """URL-safe base64 编码（无 padding）。"""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    """URL-safe base64 解码（自动补 padding）。"""
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s)


def issue_anonymous_token(
    user_id: str | None = None,
    ttl_hours: int | None = None,
) -> str:
    """签发匿名 token。

    Args:
        user_id: 用户标识，None 时自动生成 anon-<uuid>
        ttl_hours: 有效期（小时），None 时用配置默认值

    Returns:
        签名后的 token 字符串
    """
    if user_id is None:
        user_id = f"anon-{uuid.uuid4().hex[:12]}"

    if ttl_hours is None:
        ttl_hours = settings.auth_token_ttl_hours

    exp = int(time.time()) + ttl_hours * 3600

    payload = {
        "user_id": user_id,
        "role": "anonymous",
        "exp": exp,
    }

    payload_json = json.dumps(payload, separators=(",", ":"))
    payload_b64 = _b64url_encode(payload_json.encode("utf-8"))

    secret = _get_secret()
    signature = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = _b64url_encode(signature)

    token = f"{payload_b64}.{sig_b64}"

    logger.info(
        "auth.token_issued",
        user_id=user_id,
        exp=exp,
        ttl_hours=ttl_hours,
    )

    return token


def verify_token(token: str) -> dict[str, Any] | None:
    """校验 token 并返回 payload。

    Args:
        token: token 字符串

    Returns:
        payload 字典（成功）或 None（失败/过期）
    """
    if not token or "." not in token:
        return None

    parts = token.split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts

    # 验证签名
    secret = _get_secret()
    expected_sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    try:
        provided_sig = _b64url_decode(sig_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, provided_sig):
        return None

    # 解析 payload
    try:
        payload_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(payload_json)
    except Exception:
        return None

    # 检查过期
    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        return None

    return payload


def is_admin_token(provided: str) -> bool:
    """检查是否为管理员 API Key。"""
    expected = (settings.api_key or "").strip()
    if not expected:
        return False
    return hmac.compare_digest(provided.encode(), expected.encode())


# ═══════════════════════════════════════════════════════════════
# 中间件
# ═══════════════════════════════════════════════════════════════


class APIKeyMiddleware(BaseHTTPMiddleware):
    """双令牌鉴权中间件。

    鉴权层级：
    1. api_key 为空 → 全部放行（MVP 模式）
    2. 公开路径 → 放行
    3. X-API-Key / Bearer <api_key> → 管理员权限
    4. Bearer <anonymous_token> → 匿名权限（受限）
    5. 无 token → 401
    """

    async def dispatch(self, request: Request, call_next):
        expected = (settings.api_key or "").strip()
        if not expected:
            return await call_next(request)

        # CORS 预检请求不携带自定义头，必须放行交给 CORSMiddleware 处理
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # 提取凭证
        provided = request.headers.get("X-API-Key") or ""
        if not provided:
            auth = request.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        if not provided:
            return JSONResponse(
                status_code=401,
                content={
                    "ok": False,
                    "error": {
                        "code": "UNAUTHORIZED",
                        "message": "Missing API key or token",
                    },
                },
            )

        # 管理员 API Key
        if is_admin_token(provided):
            request.state.user_id = "admin"
            request.state.user_role = "admin"
            return await call_next(request)

        # 匿名 token
        payload = verify_token(provided)
        if payload is not None:
            user_id = payload.get("user_id", "anonymous")
            role = payload.get("role", "anonymous")

            # 检查管理员专用端点
            if any(path.startswith(p) for p in ADMIN_ONLY_PREFIXES):
                return JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "error": {
                            "code": "FORBIDDEN",
                            "message": "Admin access required for this endpoint",
                        },
                    },
                )

            request.state.user_id = user_id
            request.state.user_role = role
            return await call_next(request)

        # 无效凭证
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Invalid or expired token",
                },
            },
        )


# ═══════════════════════════════════════════════════════════════
# FastAPI 依赖注入（可选使用）
# ═══════════════════════════════════════════════════════════════


def get_current_user(request: Request) -> dict[str, str]:
    """从 request.state 获取当前用户信息。

    用于端点函数中获取 user_id：
        @router.post("/feedback")
        def feedback(request: Request, ...):
            user = get_current_user(request)
            user_id = user["user_id"]
    """
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "user_role", None)

    if not user_id:
        # 鉴权未启用（MVP 模式）或公开路径
        return {"user_id": "anonymous", "role": "anonymous"}

    return {"user_id": user_id, "role": role}
