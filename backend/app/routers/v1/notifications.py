"""Notifications Endpoint - 生成真实通知流.

GET  /api/v1/notifications
POST /api/v1/notifications/read

聚合通知类型：
- new_project : projects 今日新建且 label = FARM / WATCH
- score       : project_history 中同一项目最新两条 score/label 有变化
- collector   : collection_logs 今日失败/错误记录

已读状态持久化在 notification_reads（按 user_id + notification_id）。

Reference:
- docs/FRONTEND_SPEC.md §3.6 通知中心
- docs/OBSERVABILITY.md
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from itertools import groupby
from typing import Any

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import get_current_user
from app.db import get_connection

router = APIRouter(tags=["notifications"])


def _utc_midnight() -> datetime:
    """今日 UTC 零点，用于「今日」窗口。"""
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


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


def _load_read_ids(conn: Any, user_id: str) -> set[str]:
    cursor = conn.execute(
        "SELECT notification_id FROM notification_reads WHERE user_id = ?",
        (user_id,),
    )
    return {str(_row_value(r, "notification_id") or "") for r in cursor.fetchall()} - {""}


def _collect_items(conn: Any, window_start: str) -> list[dict[str, Any]]:
    """从业务表聚合通知条目（不含已读状态）。"""
    items: list[dict[str, Any]] = []

    # ── 1. 今日新 FARM / 高分项目 ────────────────────────────────
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
                "link": {"label": "查看项目", "href": f"/project/{pid}"},
            }
        )

    # ── 2. 评分变化（project_history 最新两条有差异）──────────────
    # 取今日有历史写入的项目，再对比各自最新两条快照。
    cursor = conn.execute(
        """
        SELECT h.id AS history_id, h.project_id, h.score, h.label, h.created_at,
               p.name AS project_name
        FROM project_history h
        LEFT JOIN projects p ON p.id = h.project_id
        WHERE h.project_id IN (
            SELECT DISTINCT project_id FROM project_history
            WHERE created_at >= ?
        )
        ORDER BY h.project_id, h.created_at DESC, h.id DESC
        """,
        (window_start,),
    )
    by_project: dict[str, list[dict[str, Any]]] = {}
    for row in cursor.fetchall():
        pid = str(_row_value(row, "project_id") or "")
        if not pid:
            continue
        by_project.setdefault(pid, []).append(
            {
                "history_id": _row_value(row, "history_id"),
                "score": _row_value(row, "score"),
                "label": _row_value(row, "label"),
                "created_at": _row_value(row, "created_at"),
                "name": _row_value(row, "project_name") or "未命名",
            }
        )

    for pid, hist in by_project.items():
        if len(hist) < 2:
            continue
        latest, previous = hist[0], hist[1]
        # 最新一条必须落在今日窗口内
        latest_created = str(latest.get("created_at") or "")
        if latest_created < window_start:
            continue
        latest_score = latest.get("score")
        prev_score = previous.get("score")
        latest_label = latest.get("label") or ""
        prev_label = previous.get("label") or ""
        if latest_score == prev_score and latest_label == prev_label:
            continue
        # 新项目首次入库也会写一条 history；只有真正「变化」才发 score 通知
        # （上面已要求至少两条）
        delta = None
        try:
            if latest_score is not None and prev_score is not None:
                delta = int(latest_score) - int(prev_score)
        except (TypeError, ValueError):
            delta = None
        if delta is None:
            direction = "变化"
            delta_text = f"{prev_score} → {latest_score}"
        elif delta > 0:
            direction = f"上升 {delta}"
            delta_text = f"{prev_score} → {latest_score}"
        elif delta < 0:
            direction = f"下降 {abs(delta)}"
            delta_text = f"{prev_score} → {latest_score}"
        else:
            direction = "标签变化"
            delta_text = f"{prev_score}（{prev_label or '—'} → {latest_label or '—'}）"

        name = latest.get("name") or "未命名"
        hid = latest.get("history_id") or latest_created
        items.append(
            {
                "id": f"score-{pid}-{hid}",
                "type": "score",
                "title": f"{name} 评分{direction}",
                "tag": "评分变化",
                "text": (
                    f"评分 {delta_text}"
                    + (
                        f" · 标签 {prev_label or '—'} → {latest_label or '—'}"
                        if prev_label != latest_label
                        else (f" · 当前标签 {latest_label}" if latest_label else "")
                    )
                ),
                "project_id": pid,
                "created_at": latest_created or _now_str(),
                "link": {"label": "查看项目", "href": f"/project/{pid}"},
            }
        )

    # ── 3. 采集器告警（今日失败记录）────────────────────────────
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
                "link": {"label": "运维台", "href": "/ops"},
            }
        )

    # 排序：新机会 > 评分变化 > 采集告警；同类型按时间倒序
    type_rank = {"new_project": 0, "score": 1, "collector": 2}
    ranked: list[dict[str, Any]] = []
    items_sorted_type = sorted(items, key=lambda x: type_rank.get(str(x.get("type")), 9))
    for _, group in groupby(items_sorted_type, key=lambda x: str(x.get("type"))):
        bucket = list(group)
        bucket.sort(key=lambda x: str(x.get("created_at") or ""), reverse=True)
        ranked.extend(bucket)
    return ranked


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


class MarkReadRequest(BaseModel):
    """标记通知已读。"""

    ids: list[str] = Field(default_factory=list, description="要标记已读的 notification_id 列表")
    all: bool = Field(False, description="为 true 时标记当前列表全部已读")


class MarkReadResponse(BaseModel):
    ok: bool = True
    data: dict = Field(..., description="标记结果")


@router.get(
    "/notifications",
    response_model=NotificationsResponse,
    summary="通知中心聚合",
    description=(
        "聚合今日新 FARM/WATCH 机会、评分变化与采集器告警的真实通知，"
        "并合并当前用户的已读状态。"
    ),
)
def get_notifications(request: Request) -> NotificationsResponse:
    """返回真实通知列表。"""
    user = get_current_user(request)
    user_id = user.get("user_id") or "anonymous"
    window_start = _window_start_str()

    conn = get_connection()
    try:
        items = _collect_items(conn, window_start)
        read_ids = _load_read_ids(conn, user_id)
    finally:
        conn.close()

    for item in items:
        item["read"] = item["id"] in read_ids

    return NotificationsResponse(
        ok=True,
        data={
            "unread_count": sum(1 for it in items if not it["read"]),
            "items": items,
        },
    )


@router.post(
    "/notifications/read",
    response_model=MarkReadResponse,
    summary="标记通知已读",
    description="按 notification_id 列表或 all=true 持久化已读状态。",
)
def mark_notifications_read(body: MarkReadRequest, request: Request) -> MarkReadResponse:
    """持久化通知已读状态。"""
    user = get_current_user(request)
    user_id = user.get("user_id") or "anonymous"

    conn = get_connection()
    try:
        ids = list(dict.fromkeys([i for i in body.ids if i]))  # 去重保序
        if body.all:
            window_start = _window_start_str()
            current = _collect_items(conn, window_start)
            ids = list(dict.fromkeys([*(i["id"] for i in current), *ids]))

        marked = 0
        for nid in ids:
            conn.execute(
                """
                INSERT INTO notification_reads (user_id, notification_id, read_at)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id, notification_id) DO UPDATE SET read_at = excluded.read_at
                """,
                (user_id, nid, _now_str()),
            )
            marked += 1
        conn.commit()
    finally:
        conn.close()

    return MarkReadResponse(ok=True, data={"marked": marked, "ids": ids})
