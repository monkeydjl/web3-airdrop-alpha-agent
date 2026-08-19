"""Notifications Endpoint - 生成真实通知流.

GET /api/v1/notifications
- 聚合「今日新 FARM/高分机会」与「采集器告警」两类真实通知
- 为前端「通知中心」页提供数据（替换原先写死的 mock）

数据源：
- new_project : projects 今日新建且 label = FARM / WATCH（高分机会）
- collector   : collection_logs 今日状态为失败/错误的记录

Reference:
- docs/FRONTEND_SPEC.md §3.6 通知中心
- docs/OBSERVABILITY.md
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.db import get_connection

router = APIRouter(tags=["notifications"])


def _utc_midnight() -> datetime:
    """今日 UTC 零点，用于「今日」窗口。"""
    return datetime.combine(date.today(), time.min, tzinfo=UTC)


def _now_str() -> str:
    return datetime.now(UTC).isoformat()


def _window_start_str() -> str:
    """返回不含 tz 后缀的时间字符串，兼容 SQLite 存的 'YYYY-MM-DD HH:MM:SS'。"""
    return _utc_midnight().strftime("%Y-%m-%d %H:%M:%S")


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """兼容 SQLite Row(Dict 风格索引) 与 Postgres dict_row。"""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


class NotificationsResponse(BaseModel):
    """通知聚合响应。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "unread_count": 3,
                    "items": [
                        {
                            "id": "ntf-xxx",
                            "type": "new_project",
                            "title": "今日新进 FARM：Nova Protocol",
                            "tag": "新机会",
                            "text": "主评分 82 · 建议参与",
                            "project_id": "00000000-0000-0000-0000-000000000000",
                            "created_at": "2026-07-26T00:00:00Z",
                            "read": False,
                            "link": {"label": "查看项目", "href": "/project/xxx"},
                        }
                    ],
                },
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="通知数据")


@router.get(
    "/notifications",
    response_model=NotificationsResponse,
    summary="通知中心聚合",
    description=(
        "聚合今日新 FARM/高分机会与采集器告警的真实通知，"
        "供前端「通知中心」页展示。"
    ),
)
def get_notifications() -> NotificationsResponse:
    """返回真实通知列表。

    Returns:
        NotificationsResponse 包含 unread_count 与 items 数组
    """
    window_start = _window_start_str()
    items: list[dict[str, Any]] = []

    conn = get_connection()
    try:
        # ── 1. 今日新 FARM / 高分项目（最有价值通知）───────────────
        cursor = conn.execute(
            "SELECT id, name, score, label, sector, created_at FROM projects "
            "WHERE created_at >= ? AND label IN ('FARM', 'WATCH') "
            "ORDER BY score DESC LIMIT 10",
            (window_start,),
        )
        for row in cursor.fetchall():
            pid = _row_value(row, "id") or ""
            name = _row_value(row, "name") or "未命名"
            label = _row_value(row, "label") or ""
            score = _row_value(row, "score") or 0
            sector = _row_value(row, "sector") or ""
            created = _row_value(row, "created_at") or _now_str()
            items.append(
                {
                    "id": f"new-{pid}",
                    "type": "new_project",
                    "title": f"今日新进 {label}：{name}",
                    "tag": label,
                    "text": (
                        f"主评分 {score}"
                        f"{' · ' + sector if sector else ''}"
                        f" · 建议{'参与' if label == 'FARM' else '观察'}"
                    ),
                    "project_id": pid,
                    "created_at": str(created),
                    "read": False,
                    "link": {"label": "查看项目", "href": f"/project/{pid}"},
                }
            )

        # ── 2. 采集器告警（今日失败记录）───────────────────────────
        cursor = conn.execute(
            "SELECT source_id, status, error_message, finished_at "
            "FROM collection_logs WHERE finished_at >= ? "
            "ORDER BY finished_at DESC LIMIT 20",
            (window_start,),
        )
        failed = [
            r
            for r in cursor.fetchall()
            if str(_row_value(r, "status") or "").lower() in ("failed", "error", "fault")
        ]
        for row in failed[:5]:
            source = _row_value(row, "source_id") or "unknown"
            err = _row_value(row, "error_message") or ""
            status = _row_value(row, "status") or ""
            finished = _row_value(row, "finished_at") or ""
            items.append(
                {
                    "id": f"col-{source}-{finished}",
                    "type": "collector",
                    "title": f"{source} 采集器失败",
                    "tag": "采集器告警",
                    "text": f"状态 {status}" + (f"：{err[:80]}" if err else ""),
                    "created_at": str(finished) if finished else _now_str(),
                    "read": False,
                    "link": {"label": "运维台", "href": "/ops"},
                }
            )
    finally:
        conn.close()

    # 排序：新项目机会优先
    items.sort(key=lambda x: 0 if x["type"] == "new_project" else 1)

    return NotificationsResponse(
        ok=True,
        data={
            "unread_count": sum(1 for it in items if not it["read"]),
            "items": items,
        },
    )
