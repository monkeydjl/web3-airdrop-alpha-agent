"""Raw data archival logic.

按保留期归档/清理采集原始数据:
- raw_projects: 超过保留期且已处理的项目 -> raw_projects_archive
- project_signals: 超过保留期的信号 -> project_signals_archive
- collection_logs: 超过保留期的日志直接删除

Reference:
- DATA_QUALITY.md 保留期与归档
- OPERATIONS.md 备份恢复与数据清理
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


@dataclass
class ArchiveResult:
    """归档操作结果统计。"""

    raw_archived: int = 0
    signals_archived: int = 0
    logs_deleted: int = 0
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_archived": self.raw_archived,
            "signals_archived": self.signals_archived,
            "logs_deleted": self.logs_deleted,
            "dry_run": self.dry_run,
        }


class RawDataArchiver:
    """采集原始数据归档器。"""

    def __init__(
        self,
        raw_retention_days: int | None = None,
        signals_retention_days: int | None = None,
        logs_retention_days: int | None = None,
        dry_run: bool = False,
    ) -> None:
        self.raw_retention_days = raw_retention_days or settings.raw_projects_retention_days
        self.signals_retention_days = signals_retention_days or settings.project_signals_retention_days
        self.logs_retention_days = logs_retention_days or settings.collection_logs_retention_days
        self.dry_run = dry_run

    def run(self, conn) -> ArchiveResult:
        """执行归档清理。

        Args:
            conn: SQLite 数据库连接

        Returns:
            ArchiveResult 统计结果
        """
        result = ArchiveResult(dry_run=self.dry_run)

        with conn:
            result.raw_archived = self._archive_raw_projects(conn)
            result.signals_archived = self._archive_project_signals(conn)
            result.logs_deleted = self._delete_collection_logs(conn)

        logger.info(
            "archive.completed",
            dry_run=self.dry_run,
            raw_archived=result.raw_archived,
            signals_archived=result.signals_archived,
            logs_deleted=result.logs_deleted,
        )

        return result

    def _cutoff(self, days: int) -> str:
        """计算保留期截止时间。"""
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return cutoff.isoformat()

    def _archive_raw_projects(self, conn) -> int:
        """将过期已处理的 raw_projects 归档。"""
        cutoff = self._cutoff(self.raw_retention_days)

        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM raw_projects
            WHERE processed = 1 AND discovered_at < ?
            """,
            (cutoff,),
        )
        count = cursor.fetchone()[0]

        if count == 0:
            return 0

        if self.dry_run:
            logger.info(
                "archive.raw_projects.dry_run",
                would_archive=count,
                cutoff=cutoff,
            )
            return count

        conn.execute(
            """
            INSERT INTO raw_projects_archive (
                raw_id, source_id, dedup_key, raw_data, discovered_at,
                processed, processed_at, project_id, discovery_score
            )
            SELECT
                raw_id, source_id, dedup_key, raw_data, discovered_at,
                processed, processed_at, project_id, discovery_score
            FROM raw_projects
            WHERE processed = 1 AND discovered_at < ?
            """,
            (cutoff,),
        )

        conn.execute(
            "DELETE FROM raw_projects WHERE processed = 1 AND discovered_at < ?",
            (cutoff,),
        )

        logger.info(
            "archive.raw_projects.archived",
            archived=count,
            cutoff=cutoff,
        )
        return count

    def _archive_project_signals(self, conn) -> int:
        """将过期的 project_signals 归档。"""
        cutoff = self._cutoff(self.signals_retention_days)

        cursor = conn.execute(
            "SELECT COUNT(*) FROM project_signals WHERE captured_at < ?",
            (cutoff,),
        )
        count = cursor.fetchone()[0]

        if count == 0:
            return 0

        if self.dry_run:
            logger.info(
                "archive.project_signals.dry_run",
                would_archive=count,
                cutoff=cutoff,
            )
            return count

        conn.execute(
            """
            INSERT INTO project_signals_archive (
                signal_id, project_id, dedup_key, signal_type,
                signal_source, signal_data, signal_strength, captured_at
            )
            SELECT
                signal_id, project_id, dedup_key, signal_type,
                signal_source, signal_data, signal_strength, captured_at
            FROM project_signals
            WHERE captured_at < ?
            """,
            (cutoff,),
        )

        conn.execute(
            "DELETE FROM project_signals WHERE captured_at < ?",
            (cutoff,),
        )

        logger.info(
            "archive.project_signals.archived",
            archived=count,
            cutoff=cutoff,
        )
        return count

    def _delete_collection_logs(self, conn) -> int:
        """删除过期的 collection_logs。"""
        cutoff = self._cutoff(self.logs_retention_days)

        cursor = conn.execute(
            "SELECT COUNT(*) FROM collection_logs WHERE started_at < ?",
            (cutoff,),
        )
        count = cursor.fetchone()[0]

        if count == 0:
            return 0

        if self.dry_run:
            logger.info(
                "archive.collection_logs.dry_run",
                would_delete=count,
                cutoff=cutoff,
            )
            return count

        conn.execute(
            "DELETE FROM collection_logs WHERE started_at < ?",
            (cutoff,),
        )

        logger.info(
            "archive.collection_logs.deleted",
            deleted=count,
            cutoff=cutoff,
        )
        return count
