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

from app.db import connection_scope

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
    data: dict[str, Any] = Field(..., description="聚合数据")


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

    with connection_scope() as conn:
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

        # ── 今日新增项目（projects.created_at）── 单次聚合同时获得全部与 FARM 项 ──
        cursor = conn.execute(
            """
            SELECT COUNT(*) AS n_total,
                   SUM(CASE WHEN label = 'FARM' THEN 1 ELSE 0 END) AS n_farm
            FROM projects
            WHERE created_at >= ? AND (source != 'historical_backfill' OR source IS NULL)
            """,
            (midnight.isoformat(sep=" "),),
        )
        proj_row = cursor.fetchone()
        data["today"]["new_projects"] = int(_row_value(proj_row, "n_total", 0) or 0)
        data["today"]["new_farm_projects"] = int(_row_value(proj_row, "n_farm", 0) or 0)

        # ── 发现队列（raw_projects）── 单次聚合汇总总数、待处理数与今日新增 ──
        try:
            cursor = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN processed = 0 THEN 1 ELSE 0 END) AS pending,
                       SUM(CASE WHEN discovered_at >= ? THEN 1 ELSE 0 END) AS today_new
                FROM raw_projects
                """,
                (midnight.isoformat(sep=" "),),
            )
            raw_summary = cursor.fetchone()
            data["discovery"]["total"] = int(_row_value(raw_summary, "total", 0) or 0)
            data["discovery"]["pending_count"] = int(_row_value(raw_summary, "pending", 0) or 0)
            data["discovery"]["today_new"] = int(_row_value(raw_summary, "today_new", 0) or 0)
        except Exception as exc:
            # raw_projects 是核心表，不像 opportunity_assessments 可能未建 —— 这里失败
            # 就是真故障。保留 0 兜底让概览页其余块照常渲染，但必须记 warning，
            # 否则面板恒显 0 而无从排查。
            logger.warning("dashboard.discovery_block_failed", error=str(exc))
            data["discovery"]["total"] = 0
            data["discovery"]["pending_count"] = 0
            data["discovery"]["today_new"] = 0

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

    return DashboardOverviewResponse(ok=True, data=data)


@router.get(
    "/dashboard/daily-flash",
    summary="获取今日 Alpha 动态速递快报",
    description="汇总今日最新测试网挖掘、FARM 头部重点项目与系统核心 Alpha 变动简讯。",
)
def get_daily_flash() -> dict[str, Any]:
    from app.db import dict_from_row

    with connection_scope() as conn:
        now = datetime.now(UTC)
        date_str = now.strftime("%Y-%m-%d")

        # 1. 统计当前活跃 FARM 数量（COUNT 查询）与 Top 3（LIMIT 3 查询，避免全表加载）
        farm_count_cursor = conn.execute(
            """
            SELECT COUNT(*) AS c
            FROM projects
            WHERE label = 'FARM' AND (source != 'historical_backfill' OR source IS NULL)
            """
        )
        active_farm_count = int(_row_value(farm_count_cursor.fetchone(), "c", 0) or 0)

        farm_cursor = conn.execute(
            """
            SELECT id, name, score, reason, sector, stage
            FROM projects
            WHERE label = 'FARM' AND (source != 'historical_backfill' OR source IS NULL)
            ORDER BY score DESC
            LIMIT 3
            """
        )
        farm_rows = [dict_from_row(r) for r in farm_cursor.fetchall()]

        # 2. Top 3 FARM picks
        top_picks = []
        for r in farm_rows:
            top_picks.append(
                {
                    "id": r["id"],
                    "name": r["name"],
                    "score": r["score"],
                    "reason": r.get("reason") or "重点推荐参与",
                    "sector": r.get("sector") or "",
                }
            )

        # 3. 今日/近期新增项目（开源测试网等）
        testnet_cursor = conn.execute(
            """
            SELECT COUNT(*) AS c FROM projects
            WHERE (source = 'github_curated' OR source = 'github' OR stage = 'testnet')
              AND (source != 'historical_backfill' OR source IS NULL)
            """
        )
        testnet_count = int(testnet_cursor.fetchone()["c"] or 0)

        # 4. 生成快讯文案
        top_names = "、".join(p["name"] for p in top_picks[:2]) if top_picks else "头部项目"
        ticker_text = (
            f"⚡ 今日 Alpha 速递 ({date_str})：全网挖掘 {active_farm_count} 个活跃 FARM 项目，"
            f"涵盖 {testnet_count} 个开源测试网与水龙头；"
            f"{top_names} 维持高优先级推荐。"
        )

        return {
            "ok": True,
            "data": {
                "date": date_str,
                "active_farm_count": active_farm_count,
                "testnet_count": testnet_count,
                "top_picks": top_picks,
                "ticker_text": ticker_text,
                "highlights": [
                    f"库中共有 {active_farm_count} 个高价值未发币 FARM 标的",
                    f"收录 {testnet_count} 个免 Key 开源测试网与水龙头交互路径",
                    "多钱包防女巫资金隔离拓扑与链上自动核销已就绪",
                ],
            },
        }
