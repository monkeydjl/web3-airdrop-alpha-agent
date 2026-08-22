"""ArchiveRunRepository — 归档运行历史（archive_runs 表）数据访问。

归档此前只有手动脚本 `scripts/archive_raw_data.py`，跑完不留任何痕迹：
- 前端 `/archive` 页只能显示"暂无运行历史接口"
- 运维无法回答"上次清理是什么时候、清掉了多少"
- 归档失败也不会留下记录

本仓储把每次 `RawDataArchiver.run()` 落一行，成功与失败都记。

Reference:
- DATABASE_DDL.md §6 数据保留策略
- app/archive.py RawDataArchiver
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import dict_from_row

logger = structlog.get_logger(__name__)

# 允许的触发来源。手动脚本、调度器、API 三种，记下来是为了能回答
# "这次清理是谁发起的"。
TRIGGER_SCHEDULER = "scheduler"
TRIGGER_MANUAL = "manual"
TRIGGER_API = "api"
VALID_TRIGGERS = frozenset({TRIGGER_SCHEDULER, TRIGGER_MANUAL, TRIGGER_API})

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"


class ArchiveRunRepository:
    """archive_runs 表数据访问。"""

    def __init__(self, conn) -> None:
        self.conn = conn

    def record(
        self,
        *,
        started_at: datetime,
        trigger: str,
        status: str,
        dry_run: bool = False,
        duration_ms: int = 0,
        raw_archived: int = 0,
        unprocessed_archived: int = 0,
        signals_archived: int = 0,
        logs_deleted: int = 0,
        raw_archive_pruned: int = 0,
        signals_archive_pruned: int = 0,
        error_message: str | None = None,
        finished_at: datetime | None = None,
    ) -> int:
        """记一次归档运行。

        `trigger` 不在白名单内时直接抛错 —— 与其在历史里留一个语义不明的值，
        不如让写入方立刻发现拼错了。
        """
        if trigger not in VALID_TRIGGERS:
            raise ValueError(f"Unknown trigger {trigger!r}, expected one of {sorted(VALID_TRIGGERS)}")

        finished = finished_at or datetime.now(UTC)
        cursor = self.conn.execute(
            """
            INSERT INTO archive_runs (
                started_at, finished_at, duration_ms, trigger, dry_run, status,
                raw_archived, unprocessed_archived, signals_archived, logs_deleted,
                raw_archive_pruned, signals_archive_pruned, error_message
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                started_at.isoformat(),
                finished.isoformat(),
                duration_ms,
                trigger,
                1 if dry_run else 0,
                status,
                raw_archived,
                unprocessed_archived,
                signals_archived,
                logs_deleted,
                raw_archive_pruned,
                signals_archive_pruned,
                error_message,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid or 0

    def list_recent(self, *, limit: int = 20) -> list[dict[str, Any]]:
        """按开始时间倒序列出最近的运行记录。

        `limit` 收敛到 1..200：上限防止一次拉爆响应，下限防止 0 或负数
        被 SQLite 当成"不限制"。
        """
        bounded = max(1, min(int(limit), 200))
        rows = self.conn.execute(
            "SELECT * FROM archive_runs ORDER BY started_at DESC, id DESC LIMIT ?",
            (bounded,),
        ).fetchall()
        return [dict_from_row(r) for r in rows]

    def latest(self) -> dict[str, Any] | None:
        """最近一次运行，没有则 None。"""
        rows = self.list_recent(limit=1)
        return rows[0] if rows else None

    def counts(self) -> dict[str, int]:
        """总运行次数 / 失败次数（用于页面顶部的概览）。"""
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS failed
            FROM archive_runs
            """,
            (STATUS_FAILED,),
        ).fetchone()
        data = dict_from_row(row) if row else {}
        return {
            "total": int(data.get("total") or 0),
            "failed": int(data.get("failed") or 0),
        }
