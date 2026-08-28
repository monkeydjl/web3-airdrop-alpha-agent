"""API Key + Anonymous Token authentication (V2, ADR-008).

双令牌鉴权体系：
1. 管理员 API Key（settings.api_key）：完整权限，通过 X-API-Key 或 Bearer header
2. 匿名 token（HMAC-SHA256 签名）：受限权限，通过 Bearer header

匿名 token 格式（无 JWT 依赖，纯 HMAC）：
    base64url(payload_json) + "." + base64url(hmac_sha256(payload, secret))

payload: {"user_id": "anon-<uuid>", "role": "anonymous", "exp": <unix_ts>}

受保护端点（需要管理员权限）：
    POST /api/v1/run, POST /api/v1/re-score, DELETE 类操作

    整前缀锁见 `ADMIN_ONLY_PREFIXES`；另有**按方法**锁的规则
    （`ADMIN_ONLY_METHOD_RULES`），用于"同一路径读开放、写受限"的情况：
    `/api/v1/collections/*` 的写操作会真的跑采集并消耗第三方配额，
    `PATCH /api/v1/projects/{id}/funding` 会改数据并触发重算，
    但两者的 `GET` 都是普通只读信息，不该一起锁掉。

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
import re
import time
import uuid
from typing import Any, cast

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

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

# 需要管理员权限的端点（匿名 token 不可访问），**不分方法**——整个前缀都锁。
ADMIN_ONLY_PREFIXES = (
    "/api/v1/run",
    "/api/v1/re-score",
    "/api/v1/quarantine",
    "/api/v1/export",
    "/api/v1/import",
    # 运行时配置快照属于运维信息：CORS 白名单、DB 后端、全部阈值与 cron、
    # LLM provider 清单。对匿名角色开放等于免费给攻击者做侦察，且历史上
    # 该端点曾直接回显明文 LLM api_key。纵深防御：即使响应已脱敏，也只给管理员。
    "/api/v1/settings",
    # 归档运行历史同样是运维信息：各表真实行数、保留期配置、调度 cron。
    # 与 /settings 一个口径 —— 前端 /archive 页本来就已经在调用 /settings/config，
    # 走的是同一条服务端注入密钥的代理路径，不影响页面可用性。
    "/api/v1/archive",
    # 调度器任务表是一份"系统几点在干活、哪些自动化关着"的地图：
    # 全部 cron 时刻 + 哪些采集源没配凭据 + 三个开关的真实值。
    # 对匿名角色开放等于告诉攻击者"这个系统 03:00 会自己动、而这几个源是瞎的"。
    # 与 /settings、/archive 同一口径（只读诊断，但内容是运维情报）。
    "/api/v1/scheduler",
)


# 按**方法**锁的规则：(方法集合, 路径正则)。
#
# 为什么需要这一层，而不是把前缀塞进 ADMIN_ONLY_PREFIXES：
#
# 1. `/api/v1/collections/sources` 是**只读**的采集源就绪状态，首页和
#    /discoveries 页都在读它。整条前缀锁掉会让匿名角色看不到"数据从哪来"，
#    而那不是敏感信息 —— 真正危险的是同一前缀下会**跑采集**的写操作。
# 2. `funding` 的路径是 `/api/v1/projects/{id}/funding`，通配段在中间，
#    前缀匹配根本表达不了；同一路径的 `GET` 也应当保持开放。
#
# 这两个口子的实测证据（2026-08-23，匿名 token）：
#   - `POST /api/v1/collections/{id}/trigger` → **200**，而且真的跑了一次采集
#     （写 raw_projects / project_signals / collection_runs 三张表，并消耗
#     第三方 API 配额）。
#   - `PATCH /api/v1/collections/{id}` → **200**，能改采集源开关与 cron。
#   - `PATCH /api/v1/projects/{id}/funding` → **200**，改融资数据并触发重算。
#
# `/collections/` 下的写操作用**方法白名单取反**（GET/HEAD/OPTIONS 之外全锁），
# 而不是逐条列出 trigger / PATCH：新加一个写端点时默认就是受保护的。
# **一个需要人记得来登记的白名单，迟早会漏掉一条。**
ADMIN_ONLY_METHOD_RULES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = (
    (
        frozenset({"POST", "PATCH", "PUT", "DELETE"}),
        re.compile(r"^/api/v1/collections(?:/|$)"),
    ),
    (
        frozenset({"POST", "PATCH", "PUT", "DELETE"}),
        re.compile(r"^/api/v1/projects/[^/]+/funding(?:/|$)"),
    ),
)


def requires_admin(method: str, path: str) -> bool:
    """这个 (方法, 路径) 是否只允许管理员访问。

    两层规则：整前缀锁（`ADMIN_ONLY_PREFIXES`，不分方法）+ 按方法锁
    （`ADMIN_ONLY_METHOD_RULES`）。抽成函数是为了让测试能直接断言判定结果，
    而不是只能通过发请求间接观察 —— 中间件里内联的 `any(...)` 没法单独验证。
    """
    if any(path.startswith(p) for p in ADMIN_ONLY_PREFIXES):
        return True
    return any(method.upper() in methods and pattern.match(path) for methods, pattern in ADMIN_ONLY_METHOD_RULES)


# ═══════════════════════════════════════════════════════════════
# Token 签发/校验
# ═══════════════════════════════════════════════════════════════


_EPHEMERAL_SECRET: bytes | None = None


def _get_secret() -> bytes:
    """获取签名密钥，空时随机生成（仅 MVP 单进程）。

    用模块级全局缓存而非函数属性：后者 mypy 无法表达（Callable 没有自定义属性），
    此前靠 `# type: ignore` 掩着。生产环境 AUTH_TOKEN_SECRET 为必填（见 config
    的 _validate_production），所以这条随机分支只在本地/测试生效。
    """
    secret = settings.auth_token_secret
    if secret:
        return secret.encode("utf-8")

    # 随机生成（进程级缓存，重启后旧 token 失效）
    global _EPHEMERAL_SECRET
    if _EPHEMERAL_SECRET is None:
        _EPHEMERAL_SECRET = os.urandom(32)
    return _EPHEMERAL_SECRET


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

    return cast(dict[str, Any], payload)


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

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
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

            # 检查管理员专用端点（整前缀 + 按方法两层规则）
            if requires_admin(request.method, path):
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
