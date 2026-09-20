"""User Preferences Router (V3, ADR-008 & ROADMAP §25.6, §25.10 / W12-08).

Endpoints:
- GET /api/v1/user/preferences: 获取当前登录用户的偏好设置
- PUT /api/v1/user/preferences: 全量更新当前用户的偏好设置
- PATCH /api/v1/user/preferences: 增量合并更新当前用户的偏好设置
- DELETE /api/v1/user/preferences: 清除当前用户的偏好设置（重置为默认值，GDPR 合规）
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_user
from app.db import get_connection
from app.repositories.user import UserRepository

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/user", tags=["user-preferences"])


class UserPreferencesData(BaseModel):
    """用户偏好数据模型（ROADMAP §25.6）。"""

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "sector_preferences": {"L2": 1.2, "Restaking": 0.8, "GameFi": 0.5},
                "risk_tolerance": 0.7,
                "preferred_stage": ["testnet"],
                "notifications": {
                    "telegram": "username_or_chatid",
                    "new_farm_alert": True,
                    "daily_digest": True,
                },
                "language": "zh",
                "theme": "dark",
            }
        },
    )

    sector_preferences: dict[str, float] = Field(
        default_factory=dict,
        description="赛道偏好权重字典（>1 偏好，<1 不偏好）",
    )
    risk_tolerance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="风险容忍度（0.0 保守，1.0 激进）",
    )
    preferred_stage: list[str] = Field(
        default_factory=list,
        description="偏好参与阶段（如 testnet, mainnet）",
    )
    notifications: dict[str, Any] = Field(
        default_factory=dict,
        description="通知偏好配置（如 telegram, new_farm_alert）",
    )
    language: str = Field(
        default="zh",
        description="语言偏好（zh/en）",
    )
    theme: str = Field(
        default="dark",
        description="界面主题（dark/light）",
    )


class UserPreferencesResponse(BaseModel):
    """用户偏好标准响应包装。"""

    ok: bool = True
    data: UserPreferencesData


class UserPreferencesPutPayload(BaseModel):
    """全量替换用户偏好载荷。"""

    model_config = ConfigDict(extra="allow")

    sector_preferences: dict[str, float] = Field(default_factory=dict)
    risk_tolerance: float = Field(default=0.5, ge=0.0, le=1.0)
    preferred_stage: list[str] = Field(default_factory=list)
    notifications: dict[str, Any] = Field(default_factory=dict)
    language: str = Field(default="zh")
    theme: str = Field(default="dark")


class UserPreferencesPatchPayload(BaseModel):
    """增量合并用户偏好载荷（所有字段可选）。"""

    model_config = ConfigDict(extra="allow")

    sector_preferences: dict[str, float] | None = None
    risk_tolerance: float | None = Field(default=None, ge=0.0, le=1.0)
    preferred_stage: list[str] | None = None
    notifications: dict[str, Any] | None = None
    language: str | None = None
    theme: str | None = None


def _get_authenticated_user_id(request: Request) -> str:
    """提取当前已认证的用户 ID，未认证或匿名用户直接 401。"""
    current_user = get_current_user(request)
    user_id = current_user.get("user_id")
    role = current_user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or user_id.startswith("anon-"):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required"},
        )
    return str(user_id)


def _ensure_user(repo: UserRepository, user_id: str) -> dict[str, Any]:
    """获取用户信息，若为 admin 且尚未在库中则自动初始化系统管理员记录。"""
    user = repo.get_by_id(user_id)
    if not user:
        if user_id == "admin":
            user = repo.create_user(
                user_id="admin",
                email="admin@local",
                password_hash="system_api_key_account",  # noqa: S106
                display_name="Administrator",
                role="admin",
            )
        else:
            raise HTTPException(
                status_code=404,
                detail={"code": "USER_NOT_FOUND", "message": "User not found"},
            )
    return user


def _parse_preferences_dict(raw: str | None) -> dict[str, Any]:
    """安全解析数据库中的 JSON 偏好字符串。"""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


@router.get(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="获取当前用户偏好设置",
    description="返回当前登录用户的偏好配置（若未设置则返回默认配置）。",
)
def get_user_preferences(request: Request) -> UserPreferencesResponse:
    user_id = _get_authenticated_user_id(request)

    with get_connection() as conn:
        repo = UserRepository(conn)
        user = _ensure_user(repo, user_id)
        raw_prefs = user.get("preferences")
        prefs_dict = _parse_preferences_dict(raw_prefs)

    logger.info("auth.preferences_read", user_id=user_id)
    return UserPreferencesResponse(ok=True, data=UserPreferencesData(**prefs_dict))


@router.put(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="全量更新当前用户偏好设置",
    description="全量替换当前登录用户的偏好配置并持久化入库。",
)
def put_user_preferences(request: Request, body: UserPreferencesPutPayload) -> UserPreferencesResponse:
    user_id = _get_authenticated_user_id(request)
    payload_dict = body.model_dump()
    json_str = json.dumps(payload_dict, ensure_ascii=False)

    with get_connection() as conn:
        repo = UserRepository(conn)
        _ensure_user(repo, user_id)
        repo.update_preferences(user_id, json_str)

    logger.info("auth.preferences_updated", user_id=user_id, mode="put")
    return UserPreferencesResponse(ok=True, data=UserPreferencesData(**payload_dict))


@router.patch(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="增量更新当前用户偏好设置",
    description="增量合并当前登录用户的偏好配置（字段级覆盖，字典级浅合并）。",
)
def patch_user_preferences(request: Request, body: UserPreferencesPatchPayload) -> UserPreferencesResponse:
    user_id = _get_authenticated_user_id(request)

    with get_connection() as conn:
        repo = UserRepository(conn)
        user = _ensure_user(repo, user_id)
        current = _parse_preferences_dict(user.get("preferences"))

        # 合并 sector_preferences（字典级浅合并）
        if body.sector_preferences is not None:
            sec_prefs = current.setdefault("sector_preferences", {})
            if isinstance(sec_prefs, dict):
                sec_prefs.update(body.sector_preferences)
            else:
                current["sector_preferences"] = body.sector_preferences

        # 合并 notifications（字典级浅合并）
        if body.notifications is not None:
            notifs = current.setdefault("notifications", {})
            if isinstance(notifs, dict):
                notifs.update(body.notifications)
            else:
                current["notifications"] = body.notifications

        # 标量与列表字段覆盖
        if body.risk_tolerance is not None:
            current["risk_tolerance"] = body.risk_tolerance
        if body.preferred_stage is not None:
            current["preferred_stage"] = body.preferred_stage
        if body.language is not None:
            current["language"] = body.language
        if body.theme is not None:
            current["theme"] = body.theme

        # 处理 extra 额外字段
        extra_fields = body.model_extra or {}
        for k, v in extra_fields.items():
            current[k] = v

        json_str = json.dumps(current, ensure_ascii=False)
        repo.update_preferences(user_id, json_str)

    logger.info("auth.preferences_updated", user_id=user_id, mode="patch")
    return UserPreferencesResponse(ok=True, data=UserPreferencesData(**current))


@router.delete(
    "/preferences",
    response_model=UserPreferencesResponse,
    summary="清除当前用户偏好设置",
    description="重置当前登录用户的偏好配置为默认值（GDPR §25.9 隐私合规）。",
)
def delete_user_preferences(request: Request) -> UserPreferencesResponse:
    user_id = _get_authenticated_user_id(request)

    with get_connection() as conn:
        repo = UserRepository(conn)
        _ensure_user(repo, user_id)
        repo.update_preferences(user_id, "{}")

    logger.info("auth.preferences_cleared", user_id=user_id)
    return UserPreferencesResponse(ok=True, data=UserPreferencesData())
