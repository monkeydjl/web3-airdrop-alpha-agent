"""Anonymous Token Issuance Endpoint (V2, ADR-008).

签发匿名 token，供 Dashboard 用户访问受保护 API。

Reference:
- ADR-008-user-system.md §V2 匿名 token
- V2_TASKS.md D1
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.auth import issue_anonymous_token
from app.config import settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["auth"])


# ═══════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════


class AnonymousTokenRequest(BaseModel):
    """匿名 token 签发请求（可选指定 user_id）。"""

    user_id: str | None = Field(
        default=None,
        description="自定义用户标识，不传则自动生成 anon-<uuid>",
    )


class AnonymousTokenResponse(BaseModel):
    """匿名 token 签发响应。"""

    access_token: str = Field(..., description="匿名 Bearer token")
    token_type: str = Field(default="Bearer", description="token 类型")
    expires_in: int = Field(..., description="有效期（秒）")
    user_id: str = Field(..., description="用户标识")


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/auth/anonymous",
    response_model=AnonymousTokenResponse,
    summary="签发匿名 token",
    description="签发一个匿名 Bearer token，用于访问受保护 API 端点。无需认证。",
)
def issue_anonymous(
    request: AnonymousTokenRequest | None = None,
) -> AnonymousTokenResponse:
    """签发匿名 token。

    - 无需任何认证即可调用
    - token 有效期由 `AUTH_TOKEN_TTL_HOURS` 控制（默认 72 小时）
    - 匿名 token 不可访问管理员专用端点（POST /run, POST /re-score 等）
    """
    user_id = request.user_id if request and request.user_id else None
    token = issue_anonymous_token(user_id=user_id)

    # 从 token payload 提取 user_id
    from app.auth import verify_token

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
        token_type="Bearer",  # noqa: S106 — OAuth2 方案名，不是密码
        expires_in=expires_in,
        user_id=actual_user_id,
    )
