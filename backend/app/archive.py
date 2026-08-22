"""Raw data archival logic.

按保留期归档/清理采集原始数据:
- raw_projects（已处理）: 超过保留期且 processed=1 -> raw_projects_archive
- raw_projects（未过阈值）: 超过更长的保留期且 processed=0 -> raw_projects_archive
- project_signals: 超过保留期的信号 -> project_signals_archive
- collection_logs: 超过保留期的日志直接删除
- 归档表自身: 超过保留期后删除（否则归档表只进不出）

关于"未过阈值"的那一档（2026-08-22 补）：
原实现只归档 `processed = 1`，实测这漏掉了大头 —— 数据库里 693 行 raw_projects
有 509 行（73%）是 `processed = 0`，且它们的 `discovery_score` **全部** < 0.3
（分析阈值），而 processed=1 的 184 行全部 ≥ 0.3。也就是说低分记录不会立项、
永远不会被标记已处理，于是永远不满足归档条件，只能无限累积。
按最近一次采集的 460 行低分记录估算，每天一轮约 1 年 17 万行 / 76 MB。
现在给它们单独一档更长的保留期（默认 90 天）：它们仍是复盘"当时为什么没立项"
的依据，所以归档而不是直接删除。

Reference:
- DATA_QUALITY.md 保留期与归档
- OPERATIONS.md 备份恢复与数据清理
- DATABASE_DDL.md §6 数据保留策略（180/365 天归档表清理此前零实现）
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog

from app.config import settings
from app.db import scalar
from app.repositories.archive_runs import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    ArchiveRunRepository,
)

logger = structlog.get_logger(__name__)


def _pick(override: int | None, default: int) -> int:
    """取显式传入的保留期，未传时回退到配置默认值。

    刻意用 `is None` 判断而不是 `override or default`：`or` 会把显式传入的
    **0 天**（合法取值，意为"立刻清理"，运维应急与测试都要用）当成"没传"而
    静默换成默认值。这个坑是写测试时踩到的 —— 一条本该失败的测试因为
    0 → 180 的回退而"通过"了，反而掩盖了正在验证的时间戳格式 bug。
    """
    return default if override is None else override


@dataclass
class ArchiveResult:
    """归档操作结果统计。"""

    raw_archived: int = 0
    unprocessed_archived: int = 0
    signals_archived: int = 0
    logs_deleted: int = 0
    raw_archive_pruned: int = 0
    signals_archive_pruned: int = 0
    dry_run: bool = False
    duration_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw_archived": self.raw_archived,
            "unprocessed_archived": self.unprocessed_archived,
            "signals_archived": self.signals_archived,
            "logs_deleted": self.logs_deleted,
            "raw_archive_pruned": self.raw_archive_pruned,
            "signals_archive_pruned": self.signals_archive_pruned,
            "dry_run": self.dry_run,
            "duration_ms": self.duration_ms,
        }

    @property
    def total_affected(self) -> int:
        """本次实际动过的行数合计（用于运行历史一眼看出有没有干活）。"""
        return (
            self.raw_archived
            + self.unprocessed_archived
            + self.signals_archived
            + self.logs_deleted
            + self.raw_archive_pruned
            + self.signals_archive_pruned
        )


class RawDataArchiver:
    """采集原始数据归档器。"""

    def __init__(
        self,
        raw_retention_days: int | None = None,
        signals_retention_days: int | None = None,
        logs_retention_days: int | None = None,
        unprocessed_retention_days: int | None = None,
        raw_archive_retention_days: int | None = None,
        signals_archive_retention_days: int | None = None,
        dry_run: bool = False,
    ) -> None:
        self.raw_retention_days = _pick(raw_retention_days, settings.raw_projects_retention_days)
        self.signals_retention_days = _pick(signals_retention_days, settings.project_signals_retention_days)
        self.logs_retention_days = _pick(logs_retention_days, settings.collection_logs_retention_days)
        self.unprocessed_retention_days = _pick(unprocessed_retention_days, settings.unprocessed_raw_retention_days)
        self.raw_archive_retention_days = _pick(raw_archive_retention_days, settings.raw_archive_retention_days)
        self.signals_archive_retention_days = _pick(
            signals_archive_retention_days, settings.signals_archive_retention_days
        )
        self.dry_run = dry_run

    def run(self, conn) -> ArchiveResult:
        """执行归档清理。

        Args:
            conn: SQLite 数据库连接

        Returns:
            ArchiveResult 统计结果
        """
        result = ArchiveResult(dry_run=self.dry_run)
        started = time.monotonic()

        # 显式提交，兼容裸 sqlite3.Connection 与 DbConnection（后者的
        # __exit__ 是 close()，用 `with conn:` 会丢弃未提交事务且误关连接）。
        try:
            result.raw_archived = self._archive_raw_projects(conn)
            result.unprocessed_archived = self._archive_unprocessed_raw_projects(conn)
            result.signals_archived = self._archive_project_signals(conn)
            result.logs_deleted = self._delete_collection_logs(conn)
            result.raw_archive_pruned = self._prune_raw_archive(conn)
            result.signals_archive_pruned = self._prune_signals_archive(conn)
            if not self.dry_run:
                conn.commit()
        except Exception:
            conn.rollback()
            raise

        result.duration_ms = int((time.monotonic() - started) * 1000)

        logger.info(
            "archive.completed",
            dry_run=self.dry_run,
            raw_archived=result.raw_archived,
            unprocessed_archived=result.unprocessed_archived,
            signals_archived=result.signals_archived,
            logs_deleted=result.logs_deleted,
            raw_archive_pruned=result.raw_archive_pruned,
            signals_archive_pruned=result.signals_archive_pruned,
            duration_ms=result.duration_ms,
        )

        return result

    def run_and_record(self, conn, *, trigger: str) -> ArchiveResult:
        """执行归档并把结果写入 `archive_runs`。

        失败也记一行（status=failed + error_message），否则"归档三天没跑成功"
        这种事在界面上看不出来 —— 只有成功记录的历史会让人误以为一切正常。
        记录本身失败不能吃掉原始异常，所以记录写入包在自己的 try 里。
        """
        started_at = datetime.now(UTC)
        try:
            result = self.run(conn)
        except Exception as exc:
            self._record_run(
                conn,
                started_at=started_at,
                trigger=trigger,
                status=STATUS_FAILED,
                result=ArchiveResult(dry_run=self.dry_run),
                error_message=str(exc)[:500],
            )
            raise
        self._record_run(
            conn,
            started_at=started_at,
            trigger=trigger,
            status=STATUS_SUCCESS,
            result=result,
            error_message=None,
        )
        return result

    def _record_run(
        self,
        conn,
        *,
        started_at: datetime,
        trigger: str,
        status: str,
        result: ArchiveResult,
        error_message: str | None,
    ) -> None:
        try:
            ArchiveRunRepository(conn).record(
                started_at=started_at,
                trigger=trigger,
                status=status,
                dry_run=result.dry_run,
                duration_ms=result.duration_ms,
                raw_archived=result.raw_archived,
                unprocessed_archived=result.unprocessed_archived,
                signals_archived=result.signals_archived,
                logs_deleted=result.logs_deleted,
                raw_archive_pruned=result.raw_archive_pruned,
                signals_archive_pruned=result.signals_archive_pruned,
                error_message=error_message,
            )
        except Exception as exc:  # pragma: no cover - 记录失败不应掩盖归档结果
            logger.warning("archive.run_record_failed", error=str(exc))

    def _cutoff(self, days: int) -> str:
        """计算保留期截止时间（ISO 8601，带时区）。

        用于 `discovered_at` / `captured_at` / `started_at` —— 这些列由应用层用
        `datetime.isoformat()` 写入，实测真实库里就是
        `'2026-08-15T14:51:16.959145+00:00'`，所以格式一致、字符串比较正确。
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return cutoff.isoformat()

    def _cutoff_db_default(self, days: int) -> str:
        """计算保留期截止时间，格式对齐 `DEFAULT CURRENT_TIMESTAMP`。

        **这里必须和 `_cutoff` 分开，否则会提前一天删数据。**
        归档表的 `archived_at` 没有应用层赋值，走的是 SQLite
        `DEFAULT CURRENT_TIMESTAMP`，写出来是 `'2026-08-22 02:08:51'` —— 用**空格**
        分隔，且没有微秒和时区。SQLite 的 TIMESTAMP 实际是 TEXT，`<` 是字符串比较：
        空格是 0x20、`T` 是 0x54，所以拿 ISO 格式的 cutoff 去比，当天写入的行会被
        判成"早于今天零点"。

        实测（保留期设为 0 天、行刚写入）：
          cutoff 用 `T` 分隔  → 命中 1 行（错，会删掉刚归档的数据）
          cutoff 用空格分隔   → 命中 0 行（对）

        空格分隔的字面量在 PostgreSQL 里同样是合法 timestamp，所以两种后端通用。
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        return cutoff.strftime("%Y-%m-%d %H:%M:%S")

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
        count = int(scalar(cursor.fetchone()) or 0)

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

    def _archive_unprocessed_raw_projects(self, conn) -> int:
        """将过期的**未过分析阈值**的 raw_projects 归档。

        与 `_archive_raw_projects` 分开，因为两者语义不同：
        - processed=1：已经变成项目了，原始快照只是溯源用，30 天够了
        - processed=0：**低于分析阈值、永远不会立项**的记录。这批占了实测数据的
          73%，如果不单独处理就永远留在主表里。给它更长的保留期（默认 90 天），
          因为它是复盘"当时为什么没把这个项目捞起来"的唯一依据。

        隔离区记录（quarantined=1）同样计入 —— 它们也不会被处理。
        """
        cutoff = self._cutoff(self.unprocessed_retention_days)

        cursor = conn.execute(
            """
            SELECT COUNT(*) FROM raw_projects
            WHERE processed = 0 AND discovered_at < ?
            """,
            (cutoff,),
        )
        count = int(scalar(cursor.fetchone()) or 0)

        if count == 0:
            return 0

        if self.dry_run:
            logger.info(
                "archive.unprocessed_raw.dry_run",
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
            WHERE processed = 0 AND discovered_at < ?
            """,
            (cutoff,),
        )

        conn.execute(
            "DELETE FROM raw_projects WHERE processed = 0 AND discovered_at < ?",
            (cutoff,),
        )

        logger.info(
            "archive.unprocessed_raw.archived",
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
        count = int(scalar(cursor.fetchone()) or 0)

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
        count = int(scalar(cursor.fetchone()) or 0)

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

    # ── 归档表自身的清理 ──────────────────────────
    #
    # DATABASE_DDL.md §6 早就写了归档表 180/365 天保留期，但此前**零实现** ——
    # 归档表只进不出，等于把无界增长从主表搬到了归档表。这两个方法补上。

    def _prune_archive_table(
        self,
        conn,
        table: str,
        retention_days: int,
        event: str,
    ) -> int:
        """按 archived_at 删除归档表中的过期行。

        `table` 只来自本类内部的字面量（两个归档表名），不接受外部输入。
        cutoff 用 `_cutoff_db_default` —— `archived_at` 由数据库默认值写入，
        格式与应用层写的列不同，详见该方法的说明。
        """
        cutoff = self._cutoff_db_default(retention_days)

        cursor = conn.execute(
            f"SELECT COUNT(*) FROM {table} WHERE archived_at < ?",  # noqa: S608 — 表名为内部字面量
            (cutoff,),
        )
        count = int(scalar(cursor.fetchone()) or 0)

        if count == 0:
            return 0

        if self.dry_run:
            logger.info(f"{event}.dry_run", would_delete=count, cutoff=cutoff)
            return count

        conn.execute(
            f"DELETE FROM {table} WHERE archived_at < ?",  # noqa: S608 — 同上
            (cutoff,),
        )

        logger.info(f"{event}.pruned", deleted=count, cutoff=cutoff)
        return count

    def _prune_raw_archive(self, conn) -> int:
        """删除 raw_projects_archive 中超过保留期的行（默认 180 天）。"""
        return self._prune_archive_table(
            conn,
            "raw_projects_archive",
            self.raw_archive_retention_days,
            "archive.raw_archive",
        )

    def _prune_signals_archive(self, conn) -> int:
        """删除 project_signals_archive 中超过保留期的行（默认 365 天）。"""
        return self._prune_archive_table(
            conn,
            "project_signals_archive",
            self.signals_archive_retention_days,
            "archive.signals_archive",
        )
