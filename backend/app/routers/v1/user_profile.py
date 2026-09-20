"""User Profile & Memory router (Roadmap §24.3 / §25.5.3 / W12-02).

Endpoints:
- GET /api/v1/user-profile: 获取当前用户的推断偏好画像（赛道亲和度向量、风险风格等）
- DELETE /api/v1/user-profile: 清除当前用户的偏好记忆（隐私与 GDPR 合规）
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import ROLE_ADMIN, get_current_user
from app.services.user_memory import UserProfileMemoryService
from app.services.user_scope import DEFAULT_USER

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["user-profile"])


class UserProfileResponse(BaseModel):
    """用户偏好画像响应."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "user_id": "default",
                    "sector_affinity": {"AI": 1.45, "L2": 1.2},
                    "risk_tolerance": "moderate",
                    "favorite_sectors": ["AI", "L2"],
                    "engagement_summary": {
                        "feedback_count": 5,
                        "interaction_count": 2,
                        "watchlist_count": 3,
                        "skip_count": 1,
                        "total_signals": 11,
                    },
                    "inferred_at": "2026-09-19T01:00:00Z",
                    "is_cleared": False,
                },
            }
        }
    )

    ok: bool = True
    data: dict[str, Any] = Field(..., description="用户画像数据")


@router.get(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="获取当前用户偏好画像与记忆向量",
    description="基于用户历史行为（反馈、参与流水、关注、跳过）动态推断偏好向量（Roadmap §24.3）。",
)
def get_user_profile(
    req: Request,
    user_id: str | None = Query(None, description="用户标识（可选，默认匿名用户）"),
) -> UserProfileResponse:
    """获取当前用户偏好画像（匿名 token 可读）."""
    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = user_id or (current_user["user_id"] if current_user["user_id"] != "anonymous" else DEFAULT_USER)
    elif current_user["user_id"] != "anonymous":
        uid = user_id or current_user["user_id"]
    else:
        uid = user_id or DEFAULT_USER
    uid = uid.strip()

    try:
        svc = UserProfileMemoryService()
        profile = svc.infer_user_profile(uid)
        return UserProfileResponse(ok=True, data=profile.to_dict())
    except Exception as e:
        logger.error("api.user_profile.failed", user_id=uid, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to infer user profile"},
        ) from e


@router.delete(
    "/user-profile",
    response_model=UserProfileResponse,
    summary="清除当前用户偏好画像记忆",
    description="一键重置当前用户的偏好记忆向量（隐私与 GDPR 合规）。",
)
def clear_user_profile(
    req: Request,
    user_id: str | None = Query(None, description="用户标识（可选，默认匿名用户）"),
) -> UserProfileResponse:
    """清除当前用户偏好画像记忆（匿名 token 可写）."""
    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = user_id or (current_user["user_id"] if current_user["user_id"] != "anonymous" else DEFAULT_USER)
    elif current_user["user_id"] != "anonymous":
        uid = user_id or current_user["user_id"]
    else:
        uid = user_id or DEFAULT_USER
    uid = uid.strip()

    try:
        svc = UserProfileMemoryService()
        svc.clear_user_profile(uid)
        profile = svc.infer_user_profile(uid)
        return UserProfileResponse(ok=True, data=profile.to_dict())
    except Exception as e:
        logger.error("api.user_profile.clear_failed", user_id=uid, error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to clear user profile"},
        ) from e
