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

import asyncio
import base64
import hashlib
import hmac
import json
import os
import re
import time
import uuid
from datetime import UTC, datetime
from typing import Any, cast

import bcrypt
import jwt
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
    "/api/v1/auth/register",   # 用户注册
    "/api/v1/auth/login",      # 用户登录
    "/api/v1/auth/refresh",    # 刷新 token
    "/api/v1/ha/status",       # HA 状态与负载均衡健康探测（公开只读）
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
    # 决策推送（ACTION_LOOP_DESIGN §2）：通道配置布尔、发送历史（目的地、
    # 频率、失败原因）与触发测试发送的入口，既是运维情报也是运维动作。
    "/api/v1/notify",
    # 领取监控的自有地址清单（ACTION_LOOP_DESIGN §5.4）。这是本表里
    # 敏感度最高的一项：一份"这个人有哪些钱包"的清单，配合公开的链上数据
    # 就能还原出完整持仓与交易史。读写都锁 —— 只锁写是不够的，泄露风险
    # 主要在读侧。
    "/api/v1/watched-wallets",
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
# RBAC 角色与权限控制 (V3, ADR-008 §2 & ROADMAP §25.2, §25.7)
# ═══════════════════════════════════════════════════════════════

ROLE_ADMIN = "admin"
ROLE_ANALYST = "analyst"
ROLE_VIEWER = "viewer"
ROLE_ANONYMOUS = "anonymous"

ALL_ROLES = (ROLE_ADMIN, ROLE_ANALYST, ROLE_VIEWER, ROLE_ANONYMOUS)

# viewer 角色禁止访问的写操作与路径（只读仪表盘角色，ROADMAP §25.2 & ADR-008 §2）
VIEWER_FORBIDDEN_RULES: tuple[tuple[frozenset[str], re.Pattern[str]], ...] = (
    # 反馈操作（ROADMAP §25.2: viewer 不可提交反馈）
    (
        frozenset({"POST"}),
        re.compile(r"^/api/v1/feedback(?:/|$)"),
    ),
    # 状态写操作（项目跳过/参与/台账/交互/关注列表/画像）
    (
        frozenset({"POST", "PATCH", "PUT", "DELETE"}),
        re.compile(r"^/api/v1/interactions(?:/|$)"),
    ),
    (
        frozenset({"POST", "DELETE"}),
        re.compile(r"^/api/v1/watchlist(?:/|$)"),
    ),
    (
        frozenset({"POST", "DELETE"}),
        re.compile(r"^/api/v1/projects/[^/]+/skip(?:/|$)"),
    ),
    (
        frozenset({"POST", "PATCH", "PUT", "DELETE"}),
        re.compile(r"^/api/v1/participation(?:/|$)"),
    ),
    (
        frozenset({"POST", "PATCH", "PUT", "DELETE"}),
        re.compile(r"^/api/v1/projects/[^/]+/participation(?:/|$)"),
    ),
    (
        frozenset({"POST", "DELETE"}),
        re.compile(r"^/api/v1/roi(?:/|$)"),
    ),
    (
        frozenset({"POST", "DELETE"}),
        re.compile(r"^/api/v1/projects/[^/]+/roi(?:/|$)"),
    ),
    (
        frozenset({"DELETE"}),
        re.compile(r"^/api/v1/user-profile(?:/|$)"),
    ),
    (
        frozenset({"POST"}),
        re.compile(r"^/api/v1/projects/[^/]+/opportunity/(?:evaluate|evidence)(?:/|$)"),
    ),
)


def check_role_permission(role: str, method: str, path: str) -> tuple[bool, str]:
    """检查指定角色是否允许执行 (method, path) 操作。

    角色权限矩阵 (ADR-008 §2 & ROADMAP §25.2):
    - admin: 全部权限
    - analyst: 查看项目、提交反馈、事后标注、re-score、管理个人资源
    - viewer: 只读 Dashboard（不可触发 run/re-score、不可提交反馈与修改数据）
    - anonymous: 查看项目、提交反馈/events（V2），不可触发 run/re-score，不可访问 admin 端点

    Returns:
        (allowed: bool, reason: str)
    """
    method = method.upper()

    # 1. 公开路径一律放行
    if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
        return True, ""

    # 2. admin 角色拥有所有权限
    if role == ROLE_ADMIN:
        return True, ""

    # 3. analyst 角色：允许 re-score，其余 admin 专属端点禁止
    if role == ROLE_ANALYST:
        if path.startswith("/api/v1/re-score"):
            return True, ""
        if requires_admin(method, path):
            return False, "Admin access required for this endpoint"
        return True, ""

    # 4. viewer 角色：只读 Dashboard（不可触发 run/re-score、不可提交反馈与修改数据）
    if role == ROLE_VIEWER:
        if requires_admin(method, path):
            return False, "Admin access required for this endpoint"
        if any(method in methods and pattern.match(path) for methods, pattern in VIEWER_FORBIDDEN_RULES):
            return False, f"Role '{ROLE_VIEWER}' is not authorized to perform {method} on {path}"
        return True, ""

    # 5. anonymous 角色：不可访问 admin 端点
    if role == ROLE_ANONYMOUS:
        if requires_admin(method, path):
            return False, "Admin access required for this endpoint"
        return True, ""

    # 未知角色默认拒绝
    return False, f"Role '{role}' is not recognized"


# ═══════════════════════════════════════════════════════════════
# 密码安全 (V3, ROADMAP §25.3.3)
# ═══════════════════════════════════════════════════════════════


def hash_password(password: str) -> str:
    """使用 bcrypt 哈希密码（cost factor 12，ROADMAP §25.3.3）。"""
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与 bcrypt 哈希是否匹配。"""
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except Exception:
        return False


def validate_password_strength(password: str) -> tuple[bool, str]:
    """密码强度检查（ROADMAP §25.3.3）：≥8 字符，含大小写字母 + 数字。"""
    if len(password) < 8:
        return False, "密码长度必须至少为 8 个字符"
    if not re.search(r"[A-Z]", password):
        return False, "密码必须包含至少一个大写字母"
    if not re.search(r"[a-z]", password):
        return False, "密码必须包含至少一个小写字母"
    if not re.search(r"[0-9]", password):
        return False, "密码必须包含至少一个数字"
    return True, ""


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


def _get_jwt_secret() -> str:
    """获取 JWT 签名密钥（字符串）。"""
    if settings.jwt_secret:
        return settings.jwt_secret
    if settings.auth_token_secret:
        return settings.auth_token_secret
    return _get_secret().hex()


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
    """签发匿名 token（V2 HMAC 格式，向后兼容）。

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
    """校验匿名 HMAC token 并返回 payload（V2，向后兼容）。

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


# ═══════════════════════════════════════════════════════════════
# JWT 体系与吊销黑名单 (V3, ADR-008 & ROADMAP §25.3.3)
# ═══════════════════════════════════════════════════════════════


_BLACKLISTED_JTIS: set[str] = set()


def issue_access_token(
    user_id: str,
    role: str,
    expires_minutes: int | None = None,
) -> tuple[str, str, int]:
    """签发 JWT Access Token（V3，ADR-008 & ROADMAP §25.3.3）。

    Returns:
        (token_str, jti, expires_in_seconds)
    """
    if expires_minutes is None:
        expires_minutes = settings.jwt_access_token_expire_minutes

    now = int(time.time())
    expires_in = expires_minutes * 60
    exp = now + expires_in
    jti = uuid.uuid4().hex

    payload = {
        "sub": user_id,
        "role": role,
        "iat": now,
        "exp": exp,
        "jti": jti,
        "type": "access",
    }

    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    logger.info("auth.access_token_issued", user_id=user_id, role=role, jti=jti, exp=exp)
    return token, jti, expires_in


def issue_refresh_token(
    user_id: str,
    expires_days: int | None = None,
) -> tuple[str, str, int]:
    """签发 JWT Refresh Token（V3，ADR-008 & ROADMAP §25.3.3）。

    Returns:
        (token_str, jti, expires_in_seconds)
    """
    if expires_days is None:
        expires_days = settings.jwt_refresh_token_expire_days

    now = int(time.time())
    expires_in = expires_days * 86400
    exp = now + expires_in
    jti = uuid.uuid4().hex

    payload = {
        "sub": user_id,
        "iat": now,
        "exp": exp,
        "jti": jti,
        "type": "refresh",
    }

    token = jwt.encode(payload, _get_jwt_secret(), algorithm="HS256")
    logger.info("auth.refresh_token_issued", user_id=user_id, jti=jti, exp=exp)
    return token, jti, expires_in


def hash_refresh_token(token: str) -> str:
    """计算 Refresh Token 的 SHA-256 哈希用于在 sessions 表持久化。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def blacklist_token_jti(
    jti: str,
    expires_at: datetime | None = None,
    conn: Any | None = None,
) -> None:
    """将 JTI 记入吊销黑名单（内存缓存 + 持久化表）。"""
    _BLACKLISTED_JTIS.add(jti)
    if expires_at is None:
        expires_at = datetime.fromtimestamp(time.time() + 7 * 86400, tz=UTC)

    from app.db import DbConnection, get_connection
    from app.repositories.user import BlacklistedJtiRepository

    def _do_write(c: DbConnection) -> None:
        repo = BlacklistedJtiRepository(c)
        repo.blacklist_jti(jti, expires_at)

    if conn is not None:
        _do_write(conn)
    else:
        try:
            with get_connection() as c:
                _do_write(c)
        except Exception as exc:
            logger.warning("auth.blacklist_persist_failed", jti=jti, error=str(exc))


def is_jti_blacklisted(jti: str, conn: Any | None = None) -> bool:
    """检查 JTI 是否已被吊销。"""
    if not jti:
        return False
    if jti in _BLACKLISTED_JTIS:
        return True

    from app.db import DbConnection, get_connection
    from app.repositories.user import BlacklistedJtiRepository

    def _do_check(c: DbConnection) -> bool:
        repo = BlacklistedJtiRepository(c)
        return repo.is_blacklisted(jti)

    try:
        if conn is not None:
            res = _do_check(conn)
        else:
            with get_connection() as c:
                res = _do_check(c)
        if res:
            _BLACKLISTED_JTIS.add(jti)
        return res
    except Exception:
        return False


def decode_and_verify_jwt(token: str, expected_type: str | None = None) -> dict[str, Any] | None:
    """校验 JWT 签名、过期时间与吊销状态。

    Args:
        token: JWT 字符串
        expected_type: 期望的 token 类型（"access" 或 "refresh"）

    Returns:
        payload 字典（成功）或 None（失败/过期/已吊销）
    """
    if not token or token.count(".") != 2:
        return None
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=["HS256"])
    except (jwt.PyJWTError, Exception):
        return None

    if expected_type and payload.get("type") != expected_type:
        return None

    jti = payload.get("jti")
    if jti and is_jti_blacklisted(jti):
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
    """双令牌与 JWT 鉴权中间件 (V2 + V3, ADR-008 & ROADMAP §25.7)。

    鉴权层级：
    1. api_key 为空且未提供凭证 → 全部放行（MVP 模式）
    2. OPTIONS 预检请求 → 放行
    3. 公开路径（PUBLIC_PREFIXES） → 放行
    4. X-API-Key / Bearer <api_key> → 管理员权限
    5. Bearer <jwt_token> → JWT 鉴权（校验 sub、role、exp、jti 黑名单）
    6. Bearer <anonymous_token> → 匿名权限（受限）
    7. 无有效凭证 → 401 UNAUTHORIZED
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        expected = (settings.api_key or "").strip()
        path = request.url.path

        # CORS 预检请求不携带自定义头，必须放行交给 CORSMiddleware 处理
        if request.method == "OPTIONS":
            return await call_next(request)

        if any(path == p or path.startswith(p + "/") for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # 提取凭证
        provided = request.headers.get("X-API-Key") or ""
        if not provided:
            auth = request.headers.get("Authorization") or ""
            if auth.lower().startswith("bearer "):
                provided = auth[7:].strip()

        # MVP 模式：若未配置 api_key 且未传任何凭证，放行
        if not expected and not provided:
            return await call_next(request)

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

        # 1. 管理员 API Key
        if is_admin_token(provided):
            request.state.user_id = "admin"
            request.state.user_role = ROLE_ADMIN
            request.state.auth_method = "api_key"
            return await call_next(request)

        # 1b. 动态可撤销 API Key (V3, ROADMAP §25.3.3)
        if provided.startswith("ak_"):
            def _verify_ak(raw_key: str) -> dict[str, Any] | None:
                from app.db import get_connection
                from app.repositories.api_key import ApiKeyRepository

                with get_connection() as conn:
                    repo = ApiKeyRepository(conn)
                    record = repo.find_active_key_by_raw(raw_key)
                    if record:
                        repo.update_last_used(record["id"])
                    return record

            # P1-4: DB 查询与 12 轮 bcrypt 计算移出主事件循环
            key_record = await asyncio.to_thread(_verify_ak, provided)
            if key_record:
                user_id = key_record["user_id"]
                role = key_record["role"]
                key_id = key_record["id"]

                # RBAC 权限检查
                allowed, reason = check_role_permission(role, request.method, path)
                if not allowed:
                    logger.warning(
                        "auth.rbac_denied",
                        user_id=user_id,
                        role=role,
                        method=request.method,
                        path=path,
                        reason=reason,
                    )
                    return JSONResponse(
                        status_code=403,
                        content={
                            "ok": False,
                            "error": {
                                "code": "FORBIDDEN",
                                "message": reason,
                            },
                        },
                    )

                logger.info("auth.api_key_authenticated", user_id=user_id, key_id=key_id, role=role)
                request.state.user_id = user_id
                request.state.user_role = role
                request.state.api_key_id = key_id
                request.state.auth_method = "api_key"
                return await call_next(request)

        # 2. JWT Access Token (V3)
        # P1-4: JWT 解密与 JTI 黑名单 DB 查询移出主事件循环
        jwt_payload = await asyncio.to_thread(decode_and_verify_jwt, provided, "access")
        if jwt_payload is not None:
            user_id = jwt_payload.get("sub", "anonymous")
            role = jwt_payload.get("role", ROLE_VIEWER)
            jti = jwt_payload.get("jti", "")

            # RBAC 权限检查
            allowed, reason = check_role_permission(role, request.method, path)
            if not allowed:
                logger.warning(
                    "auth.rbac_denied",
                    user_id=user_id,
                    role=role,
                    method=request.method,
                    path=path,
                    reason=reason,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "error": {
                            "code": "FORBIDDEN",
                            "message": reason,
                        },
                    },
                )

            request.state.user_id = user_id
            request.state.user_role = role
            request.state.jwt_jti = jti
            request.state.auth_method = "jwt"
            return await call_next(request)

        # 3. 匿名 token (V2 HMAC)
        payload = verify_token(provided)
        if payload is not None:
            user_id = payload.get("user_id", "anonymous")
            role = payload.get("role", ROLE_ANONYMOUS)

            # RBAC 权限检查
            allowed, reason = check_role_permission(role, request.method, path)
            if not allowed:
                logger.warning(
                    "auth.rbac_denied",
                    user_id=user_id,
                    role=role,
                    method=request.method,
                    path=path,
                    reason=reason,
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "ok": False,
                        "error": {
                            "code": "FORBIDDEN",
                            "message": reason,
                        },
                    },
                )

            request.state.user_id = user_id
            request.state.user_role = role
            request.state.auth_method = "anonymous"
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


def get_current_user(request: Request) -> dict[str, Any]:
    """从 request.state 获取当前用户信息。

    用于端点函数中获取 user_id：
        @router.post("/feedback")
        def feedback(request: Request, ...):
            user = get_current_user(request)
            user_id = user["user_id"]
    """
    user_id = getattr(request.state, "user_id", None)
    role = getattr(request.state, "user_role", None)
    auth_method = getattr(request.state, "auth_method", None)
    jwt_jti = getattr(request.state, "jwt_jti", None)

    if not user_id:
        return {"user_id": "anonymous", "role": ROLE_ANONYMOUS, "auth_method": "none", "jwt_jti": None}

    return {
        "user_id": user_id,
        "role": role or ROLE_ANONYMOUS,
        "auth_method": auth_method or "unknown",
        "jwt_jti": jwt_jti,
    }


def require_role(*allowed_roles: str):
    """FastAPI 依赖注入：检查当前请求用户是否属于指定角色之一。

    用于端点函数显式限定访问角色：
        @router.post("/re-score", dependencies=[Depends(require_role("admin", "analyst"))])
        def re_score(...):
            ...
    """
    from fastapi import HTTPException

    def _dependency(request: Request) -> str:
        role = getattr(request.state, "user_role", ROLE_ANONYMOUS)
        if role not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": f"Role '{role}' is not authorized to access this resource",
                },
            )
        return role

    return _dependency

