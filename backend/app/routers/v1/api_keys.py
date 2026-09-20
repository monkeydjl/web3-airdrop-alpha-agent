"""API Keys Router (V3, ADR-008 & ROADMAP §25.3.3, §25.10 / W12-09).

Endpoints:
- GET /api/v1/api-keys: 列出当前用户的 API Key（脱敏显示）
- POST /api/v1/api-keys: 创建新的 API Key（返回唯一一次展示的完整 raw_key）
- DELETE /api/v1/api-keys/{key_id}: 撤销指定的 API Key
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import ALL_ROLES, ROLE_ADMIN, get_current_user, hash_password
from app.db import get_connection
from app.repositories.api_key import ApiKeyRepository

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])


class ApiKeyItem(BaseModel):
    """API Key 条目（已脱敏，不含明文密钥与哈希）。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "key_1a2b3c4d5e6f7081",
                "user_id": "usr_9f1a2d3b4c5e",
                "name": "CI Pipeline Key",
                "role": "analyst",
                "last_used_at": "2026-09-19T10:30:00Z",
                "expires_at": "2027-09-19T10:00:00Z",
                "is_revoked": False,
                "created_at": "2026-09-19T10:00:00Z",
            }
        }
    )

    id: str
    user_id: str
    name: str
    role: str
    last_used_at: str | None = None
    expires_at: str | None = None
    is_revoked: bool
    created_at: str | None = None


class ApiKeyCreatedData(BaseModel):
    """新建 API Key 响应数据（包含且仅包含一次的明文 raw_key）。"""

    key: ApiKeyItem
    raw_key: str = Field(..., description="完整明文 API Key，仅在创建时返回一次，请立即安全保存")


class ApiKeyCreatePayload(BaseModel):
    """创建 API Key 请求体。"""

    name: str = Field(..., min_length=1, max_length=64, description="API Key 描述名称")
    role: str | None = Field(default=None, description="绑定的角色（默认与当前用户一致，非 admin 不可越权）")
    expires_in_days: int | None = Field(default=None, ge=1, le=365, description="有效天数（1-365天，可选）")


class ApiKeyListResponse(BaseModel):
    """API Key 列表响应。"""

    ok: bool = True
    data: list[ApiKeyItem]


class ApiKeyCreateResponse(BaseModel):
    """API Key 创建响应。"""

    ok: bool = True
    data: ApiKeyCreatedData


class ApiKeyRevokeResponse(BaseModel):
    """API Key 撤销响应。"""

    ok: bool = True
    data: dict[str, Any]


def _get_auth_context(request: Request) -> tuple[str, str]:
    """提取已认证用户 ID 与角色，未认证或匿名用户直接 401。"""
    user = get_current_user(request)
    user_id = user.get("user_id")
    role = user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or user_id.startswith("anon-"):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required"},
        )
    return str(user_id), str(role)


def _to_api_key_item(record: dict[str, Any]) -> ApiKeyItem:
    """转换为脱敏的 ApiKeyItem。"""
    return ApiKeyItem(
        id=str(record["id"]),
        user_id=str(record["user_id"]),
        name=str(record["name"]),
        role=str(record["role"]),
        last_used_at=str(record["last_used_at"]) if record.get("last_used_at") else None,
        expires_at=str(record["expires_at"]) if record.get("expires_at") else None,
        is_revoked=bool(record.get("is_revoked")),
        created_at=str(record["created_at"]) if record.get("created_at") else None,
    )


@router.get(
    "",
    response_model=ApiKeyListResponse,
    summary="列出当前用户的 API Key",
    description="返回当前登录用户的 API Key 列表（脱敏）。admin 用户可通过 ?all=true 查看全仓 Key。",
)
def list_api_keys(
    request: Request,
    all: bool = Query(False, description="是否查看所有用户的 Key（仅 admin 权限有效）"),
    include_revoked: bool = Query(False, description="是否包含已撤销的 Key"),
) -> ApiKeyListResponse:
    user_id, role = _get_auth_context(request)

    with get_connection() as conn:
        repo = ApiKeyRepository(conn)
        if all and role == ROLE_ADMIN:
            records = repo.list_all(include_revoked=include_revoked)
        else:
            records = repo.list_by_user(user_id, include_revoked=include_revoked)

    items = [_to_api_key_item(r) for r in records]
    return ApiKeyListResponse(ok=True, data=items)


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    summary="创建新 API Key",
    description="生成新的可撤销 API Key。原始密钥仅在此处返回一次，请立即保存。",
)
def create_api_key(
    request: Request,
    body: ApiKeyCreatePayload,
) -> ApiKeyCreateResponse:
    user_id, user_role = _get_auth_context(request)

    # 确定 Key 的角色权限
    if body.role:
        if body.role not in ALL_ROLES:
            raise HTTPException(
                status_code=422,
                detail={"code": "VALIDATION_ERROR", "message": f"Invalid role: {body.role}"},
            )
        # 权限边界约束：非 admin 用户不能授予超越自身角色的权限
        if user_role != ROLE_ADMIN and body.role != user_role:
            raise HTTPException(
                status_code=403,
                detail={
                    "code": "FORBIDDEN",
                    "message": "Non-admin users cannot grant roles other than their own",
                },
            )
        target_role = body.role
    else:
        target_role = user_role

    # 生成 Key 结构：ak_{16_hex}_{32_secret}
    key_id_hex = uuid.uuid4().hex[:16]
    key_id = f"key_{key_id_hex}"
    secret = secrets.token_urlsafe(32)
    raw_key = f"ak_{key_id_hex}_{secret}"
    key_hash = hash_password(raw_key)

    expires_at: datetime | None = None
    if body.expires_in_days:
        expires_at = datetime.now(UTC) + timedelta(days=body.expires_in_days)

    with get_connection() as conn:
        repo = ApiKeyRepository(conn)
        record = repo.create_key(
            key_id=key_id,
            user_id=user_id,
            name=body.name,
            key_hash=key_hash,
            role=target_role,
            expires_at=expires_at,
        )

    logger.info("auth.api_key_created", user_id=user_id, key_id=key_id, role=target_role)

    item = _to_api_key_item(record)
    return ApiKeyCreateResponse(
        ok=True,
        data=ApiKeyCreatedData(
            key=item,
            raw_key=raw_key,
        ),
    )


@router.delete(
    "/{key_id}",
    response_model=ApiKeyRevokeResponse,
    summary="撤销指定的 API Key",
    description="撤销指定的 API Key。非 admin 用户仅可撤销属于自身的 Key。",
)
def revoke_api_key(
    request: Request,
    key_id: str,
) -> ApiKeyRevokeResponse:
    user_id, user_role = _get_auth_context(request)

    with get_connection() as conn:
        repo = ApiKeyRepository(conn)
        record = repo.get_by_id(key_id)
        if not record or record.get("is_revoked"):
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "API key not found or already revoked"},
            )

        # 归属检查：非 admin 只能撤销归属于自身的 Key
        if user_role != ROLE_ADMIN and record["user_id"] != user_id:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": "API key not found or already revoked"},
            )

        repo.revoke_key(key_id)

    logger.info("auth.api_key_revoked", user_id=user_id, key_id=key_id)
    return ApiKeyRevokeResponse(
        ok=True,
        data={"message": "API key revoked successfully", "key_id": key_id},
    )
