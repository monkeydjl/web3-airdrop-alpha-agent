"""User Data & Account Lifecycle Router (V3, ADR-008 & ROADMAP §25.9, §25.10 / W12-11).

Endpoints:
- GET /api/v1/user/data: 导出当前登录用户的所有个人数据（JSON 格式，GDPR 数据可携带权）
- DELETE /api/v1/user/account: 注销当前用户账户（去标识化反馈、硬删除 events/私有数据、吊销凭据，GDPR 被遗忘权）
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import (
    blacklist_token_jti,
    get_current_user,
)
from app.db import DbConnection, dict_from_row, get_connection
from app.repositories.user import UserRepository

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/user", tags=["user-data"])


class UserExportData(BaseModel):
    """用户完整导出数据（ROADMAP §25.9）。"""

    model_config = ConfigDict(extra="allow")

    exported_at: str = Field(..., description="导出时间（ISO 8601 UTC）")
    user: dict[str, Any] = Field(..., description="用户基本资料（排除密码哈希）")
    preferences: dict[str, Any] = Field(default_factory=dict, description="用户偏好配置")
    feedback: list[dict[str, Any]] = Field(default_factory=list, description="用户提交的历史评分反馈")
    events: list[dict[str, Any]] = Field(default_factory=list, description="用户行为埋点事件")
    watchlist: list[dict[str, Any]] = Field(default_factory=list, description="用户关注列表")
    project_skips: list[dict[str, Any]] = Field(default_factory=list, description="用户跳过标记")
    interactions: list[dict[str, Any]] = Field(default_factory=list, description="用户交互记录")
    participation_plans: list[dict[str, Any]] = Field(default_factory=list, description="用户参与计划")
    participation_tasks: list[dict[str, Any]] = Field(default_factory=list, description="用户参与任务")
    roi_entries: list[dict[str, Any]] = Field(default_factory=list, description="用户投入台账")
    roi_outcomes: list[dict[str, Any]] = Field(default_factory=list, description="用户产出台账")
    api_keys: list[dict[str, Any]] = Field(default_factory=list, description="用户 API 密钥（排除密钥哈希）")


class UserExportResponse(BaseModel):
    ok: bool = True
    data: UserExportData


class UserDeleteResponse(BaseModel):
    ok: bool = True
    data: dict[str, Any]


def _get_authenticated_user(request: Request) -> dict[str, Any]:
    """提取当前已认证的用户，未认证或匿名用户直接 401。"""
    current_user = get_current_user(request)
    user_id = current_user.get("user_id")
    role = current_user.get("role")

    if not user_id or user_id == "anonymous" or role == "anonymous" or str(user_id).startswith("anon-"):
        raise HTTPException(
            status_code=401,
            detail={"code": "UNAUTHORIZED", "message": "Authentication required"},
        )
    return current_user


def _safe_query(conn: DbConnection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict_from_row(r) for r in rows]
    except Exception:
        return []


def _safe_execute(conn: DbConnection, sql: str, params: tuple[Any, ...]) -> int:
    try:
        cursor = conn.execute(sql, params)
        return int(cursor.rowcount or 0)
    except Exception:
        return 0


@router.get(
    "/data",
    response_model=UserExportResponse,
    summary="导出当前用户所有数据",
    description="导出当前登录用户的所有个人数据（反馈、events、偏好、关注、交互等）为 JSON（GDPR §25.9 数据可携带权）。",
)
def export_user_data(request: Request) -> UserExportResponse:
    auth_user = _get_authenticated_user(request)
    user_id = str(auth_user["user_id"])

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user_row = user_repo.get_by_id(user_id)
        if not user_row:
            if user_id == "admin":
                user_row = {
                    "id": "admin",
                    "email": "admin@local",
                    "display_name": "Administrator",
                    "role": "admin",
                    "is_active": 1,
                    "preferences": "{}",
                    "last_login_at": None,
                    "created_at": None,
                    "updated_at": None,
                }
            else:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "USER_NOT_FOUND", "message": "User not found"},
                )

        # 剥离敏感哈希
        safe_user = {
            "id": user_row.get("id"),
            "email": user_row.get("email"),
            "display_name": user_row.get("display_name"),
            "role": user_row.get("role"),
            "is_active": bool(user_row.get("is_active")),
            "last_login_at": str(user_row["last_login_at"]) if user_row.get("last_login_at") else None,
            "created_at": str(user_row["created_at"]) if user_row.get("created_at") else None,
            "updated_at": str(user_row["updated_at"]) if user_row.get("updated_at") else None,
        }

        # 解析 preferences
        raw_prefs = user_row.get("preferences")
        prefs_dict = {}
        if raw_prefs and str(raw_prefs).strip():
            try:
                parsed = json.loads(raw_prefs)
                if isinstance(parsed, dict):
                    prefs_dict = parsed
            except Exception:
                pass

        feedback_rows = _safe_query(
            conn,
            "SELECT * FROM feedback WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        events_rows = _safe_query(
            conn,
            "SELECT * FROM events WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        watchlist_rows = _safe_query(
            conn,
            "SELECT * FROM watchlist WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        skips_rows = _safe_query(
            conn,
            "SELECT * FROM project_skips WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        interactions_rows = _safe_query(
            conn,
            "SELECT * FROM interactions WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        plan_rows = _safe_query(
            conn,
            "SELECT * FROM participation_plans WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        task_rows = _safe_query(
            conn,
            "SELECT * FROM participation_tasks WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        roi_entry_rows = _safe_query(
            conn,
            "SELECT * FROM roi_entries WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        roi_outcome_rows = _safe_query(
            conn,
            "SELECT * FROM roi_outcomes WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )
        # API Keys：脱敏排除 key_hash
        api_keys_rows = _safe_query(
            conn,
            "SELECT id, name, role, last_used_at, expires_at, is_revoked, created_at FROM api_keys WHERE user_id = ? ORDER BY id DESC",
            (user_id,),
        )

    logger.info("auth.data_exported", user_id=user_id)
    return UserExportResponse(
        ok=True,
        data=UserExportData(
            exported_at=datetime.now(UTC).isoformat(),
            user=safe_user,
            preferences=prefs_dict,
            feedback=feedback_rows,
            events=events_rows,
            watchlist=watchlist_rows,
            project_skips=skips_rows,
            interactions=interactions_rows,
            participation_plans=plan_rows,
            participation_tasks=task_rows,
            roi_entries=roi_entry_rows,
            roi_outcomes=roi_outcome_rows,
            api_keys=api_keys_rows,
        ),
    )


@router.delete(
    "/account",
    response_model=UserDeleteResponse,
    summary="注销并删除当前用户账户",
    description="彻底注销当前登录用户：去标识化反馈样本、硬删除 events 行为日志及个人私有数据，吊销所有 Token 与会话（GDPR §25.9 被遗忘权）。",
)
def delete_user_account(request: Request) -> UserDeleteResponse:
    auth_user = _get_authenticated_user(request)
    user_id = str(auth_user["user_id"])
    jwt_jti = auth_user.get("jwt_jti")

    with get_connection() as conn:
        user_repo = UserRepository(conn)
        user = user_repo.get_by_id(user_id)
        if not user and user_id != "admin":
            raise HTTPException(
                status_code=404,
                detail={"code": "USER_NOT_FOUND", "message": "User not found"},
            )

        # 1. 反馈数据去标识化（保留样本供模型权重校准，user_id 置 NULL）
        deidentified_feedback = _safe_execute(
            conn,
            "UPDATE feedback SET user_id = NULL WHERE user_id = ?",
            (user_id,),
        )

        # 2. 行为日志与私有数据硬删除
        deleted_events = _safe_execute(conn, "DELETE FROM events WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM watchlist WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM project_skips WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM interactions WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM notification_reads WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM participation_tasks WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM participation_plans WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM roi_entries WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM roi_outcomes WHERE user_id = ?", (user_id,))

        # 3. 吊销并删除会话与 API Keys
        _safe_execute(conn, "DELETE FROM api_keys WHERE user_id = ?", (user_id,))
        _safe_execute(conn, "DELETE FROM sessions WHERE user_id = ?", (user_id,))

        # 4. 删除用户主体记录（释放邮箱）
        if user:
            user_repo.delete_user(user_id)

        # 5. 黑名单吊销当前 Token 的 JTI
        if jwt_jti:
            blacklist_token_jti(jwt_jti, conn=conn)

        conn.commit()

    logger.info(
        "auth.account_deleted",
        user_id=user_id,
        deidentified_feedback=deidentified_feedback,
        deleted_events=deleted_events,
    )
    return UserDeleteResponse(
        ok=True,
        data={
            "user_id": user_id,
            "status": "deleted",
            "message": "Account successfully deleted and data de-identified/erased",
            "deidentified_feedback_count": deidentified_feedback,
            "deleted_events_count": deleted_events,
        },
    )
