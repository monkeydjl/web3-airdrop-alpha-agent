"""Dashboard Overview Endpoint - 聚合「今日流水线」真实数据.

GET /api/v1/dashboard/overview
- 聚合发现队列 / 影子引擎 / 今日采集运行的真实数据
- 为 Dashboard「今日流水线」卡片提供数据（替换原先写死的 mock 值）

Reference:
- docs/FRONTEND_SPEC.md §3.2 Dashboard
- docs/OBSERVABILITY.md
"""

from datetime import UTC, datetime, time
from typing import Any

import structlog
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.db import get_connection

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["dashboard"])


def _utc_midnight() -> datetime:
    """今日 UTC 零点，用于「今日」窗口。"""
    return datetime.combine(datetime.now(UTC).date(), time.min, tzinfo=UTC)


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


class DashboardOverviewResponse(BaseModel):
    """Dashboard 概览聚合响应。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "today": {
                        "collection_runs": {"total": 5, "success": 4, "failed": 1},
                        "new_projects": 8,
                        "new_farm_projects": 2,
                    },
                    "discovery": {
                        "pending_count": 12,
                        "today_new": 6,
                        "total": 180,
                    },
                    "shadow": {
                        "saved_today": 3,
                        "label_counts": {"FARM": 1, "WATCH": 2, "IGNORE": 0},
                    },
                },
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="聚合数据")


@router.get(
    "/dashboard/overview",
    response_model=DashboardOverviewResponse,
    summary="Dashboard 今日概览聚合",
    description=("聚合今日采集运行、发现队列与影子引擎评估的真实数据，供 Dashboard「今日流水线」卡片展示。"),
)
def get_dashboard_overview() -> DashboardOverviewResponse:
    """返回今日概览聚合数据。

    Returns:
        DashboardOverviewResponse 包含 today/discovery/shadow 三个聚合块
    """
    midnight = _utc_midnight()

    data: dict[str, Any] = {
        "today": {"collection_runs": {"total": 0, "success": 0, "failed": 0}},
        "discovery": {"pending_count": 0, "today_new": 0, "total": 0},
        "shadow": {"saved_today": 0, "label_counts": {"FARM": 0, "WATCH": 0, "IGNORE": 0}},
    }

    conn = get_connection()
    try:
        # ── 今日采集运行（collection_logs）──────────────────────────
        # 注意 started_at 存储格式可能是 ISO 字符串或 TIMESTAMP，统一用字符串前缀比较。
        cursor = conn.execute(
            "SELECT status, COUNT(*) AS n FROM collection_logs WHERE started_at >= ? GROUP BY status",
            (midnight.isoformat(sep=" "),),
        )
        runs_total = 0
        runs_success = 0
        runs_failed = 0
        for row in cursor.fetchall():
            status = _row_value(row, "status") or ""
            n = int(_row_value(row, "n", 0) or 0)
            runs_total += n
            if status and status.lower() in ("success", "ok", "completed", "done"):
                runs_success += n
            elif status and status.lower() in ("failed", "error", "fault", "failure"):
                runs_failed += n
        data["today"]["collection_runs"] = {
            "total": runs_total,
            "success": runs_success,
            "failed": runs_failed,
        }

        # ── 今日新增项目（projects.created_at）──────────────────────
        cursor = conn.execute(
            "SELECT COUNT(*) AS n FROM projects WHERE created_at >= ?",
            (midnight.isoformat(sep=" "),),
        )
        today_new = int(_row_value(cursor.fetchone(), "n", 0) or 0)
        data["today"]["new_projects"] = today_new

        cursor = conn.execute(
            "SELECT COUNT(*) AS n FROM projects WHERE created_at >= ? AND label = 'FARM'",
            (midnight.isoformat(sep=" "),),
        )
        today_farm = int(_row_value(cursor.fetchone(), "n", 0) or 0)
        data["today"]["new_farm_projects"] = today_farm

        # ── 发现队列（raw_projects）─────────────────────────────────
        cursor = conn.execute("SELECT COUNT(*) AS n FROM raw_projects")
        discovery_total = int(_row_value(cursor.fetchone(), "n", 0) or 0)
        data["discovery"]["total"] = discovery_total

        try:
            cursor = conn.execute("SELECT COUNT(*) AS n FROM raw_projects WHERE processed = 0")
            discovery_pending = int(_row_value(cursor.fetchone(), "n", 0) or 0)
        except Exception:
            discovery_pending = 0
        data["discovery"]["pending_count"] = discovery_pending

        # 今日新增发现（discovered_at）
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) AS n FROM raw_projects WHERE discovered_at >= ?",
                (midnight.isoformat(sep=" "),),
            )
            discovery_today = int(_row_value(cursor.fetchone(), "n", 0) or 0)
        except Exception:
            discovery_today = 0
        data["discovery"]["today_new"] = discovery_today

        # ── 影子引擎（opportunity_assessments）─────────────────────
        try:
            cursor = conn.execute(
                "SELECT public_label, COUNT(*) AS n FROM opportunity_assessments "
                "WHERE created_at >= ? GROUP BY public_label",
                (midnight.isoformat(sep=" "),),
            )
            saved_today = 0
            label_counts = {"FARM": 0, "WATCH": 0, "IGNORE": 0}
            for row in cursor.fetchall():
                label = _row_value(row, "public_label") or ""
                n = int(_row_value(row, "n", 0) or 0)
                saved_today += n
                if label in label_counts:
                    label_counts[label] = n
            data["shadow"]["saved_today"] = saved_today
            data["shadow"]["label_counts"] = label_counts
        except Exception as exc:
            # opportunity_assessments 表可能尚未建（影子引擎未运行过）。
            # 记 debug 而不是静默 pass：否则真正的 SQL/schema 故障也会被吞掉，
            # 表现为面板恒显 0 而无从排查。
            logger.debug("dashboard.shadow_block_unavailable", error=str(exc))
    finally:
        conn.close()

    return DashboardOverviewResponse(ok=True, data=data)
