"""Tests for raw data archival logic.

Reference:
- backend/app/archive.py
- scripts/archive_raw_data.py
"""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.archive import ArchiveResult, RawDataArchiver
from app.db import init_db
from app.repositories.archive_runs import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULER,
    ArchiveRunRepository,
)


@pytest.fixture
def db_conn():
    """创建临时内存数据库并初始化表结构。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def _insert_raw_project(conn, discovered_at, processed=1):
    """插入一条 raw_projects 记录。"""
    raw_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, processed_at, project_id, discovery_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            raw_id,
            "defillama",
            f"project-{raw_id}",
            '{"name": "Test"}',
            discovered_at.isoformat(),
            processed,
            discovered_at.isoformat() if processed else None,
            f"proj-{raw_id}",
            0.5,
        ),
    )
    conn.commit()
    return raw_id


def _insert_signal(conn, captured_at):
    """插入一条 project_signals 记录。"""
    signal_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO project_signals (
            signal_id, project_id, dedup_key, signal_type,
            signal_source, signal_data, signal_strength, captured_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            signal_id,
            "proj-1",
            "dedup-1",
            "tvl",
            "defillama",
            '{"tvl": 1000000}',
            0.8,
            captured_at.isoformat(),
        ),
    )
    conn.commit()
    return signal_id


def _insert_collection_log(conn, started_at):
    """插入一条 collection_logs 记录。"""
    log_id = uuid.uuid4().hex
    conn.execute(
        """
        INSERT INTO collection_logs (
            log_id, source_id, started_at, finished_at,
            items_collected, status
        ) VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            log_id,
            "defillama",
            started_at.isoformat(),
            (started_at + timedelta(minutes=1)).isoformat(),
            10,
            "success",
        ),
    )
    conn.commit()
    return log_id


def _count_raw_projects(conn):
    return conn.execute("SELECT COUNT(*) FROM raw_projects").fetchone()[0]


def _count_signals(conn):
    return conn.execute("SELECT COUNT(*) FROM project_signals").fetchone()[0]


def _count_logs(conn):
    return conn.execute("SELECT COUNT(*) FROM collection_logs").fetchone()[0]


def _count_raw_archive(conn):
    return conn.execute("SELECT COUNT(*) FROM raw_projects_archive").fetchone()[0]


def _count_signals_archive(conn):
    return conn.execute("SELECT COUNT(*) FROM project_signals_archive").fetchone()[0]


class TestRawDataArchiver:
    """Test RawDataArchiver."""

    def test_dry_run_does_not_modify(self, db_conn):
        """dry-run 只统计不修改数据库。"""
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old)
        _insert_signal(db_conn, old)
        _insert_collection_log(db_conn, old)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            signals_retention_days=30,
            logs_retention_days=30,
            dry_run=True,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
        assert result.signals_archived == 1
        assert result.logs_deleted == 1
        assert _count_raw_projects(db_conn) == 1
        assert _count_signals(db_conn) == 1
        assert _count_logs(db_conn) == 1
        assert _count_raw_archive(db_conn) == 0
        assert _count_signals_archive(db_conn) == 0

    def test_archive_expired_records(self, db_conn):
        """过期记录被正确归档/删除。"""
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old)
        _insert_signal(db_conn, old)
        _insert_collection_log(db_conn, old)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            signals_retention_days=30,
            logs_retention_days=30,
            dry_run=False,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
        assert result.signals_archived == 1
        assert result.logs_deleted == 1
        assert _count_raw_projects(db_conn) == 0
        assert _count_signals(db_conn) == 0
        assert _count_logs(db_conn) == 0
        assert _count_raw_archive(db_conn) == 1
        assert _count_signals_archive(db_conn) == 1

    def test_keep_recent_records(self, db_conn):
        """未过期记录不被处理。"""
        recent = datetime.now(UTC) - timedelta(days=5)
        _insert_raw_project(db_conn, recent)
        _insert_signal(db_conn, recent)
        _insert_collection_log(db_conn, recent)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            signals_retention_days=30,
            logs_retention_days=30,
            dry_run=False,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 0
        assert result.signals_archived == 0
        assert result.logs_deleted == 0
        assert _count_raw_projects(db_conn) == 1
        assert _count_signals(db_conn) == 1
        assert _count_logs(db_conn) == 1

    def test_unprocessed_kept_under_its_own_retention(self, db_conn):
        """未处理记录走**自己那档**更长的保留期，不跟着 30 天走。

        原实现只归档 processed=1，未处理记录永远留在主表。现在它们有自己的
        保留期（默认 90 天）：40 天的还不到期，所以这一步仍只归档已处理的那条。
        """
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        _insert_raw_project(db_conn, old, processed=0)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            unprocessed_retention_days=90,
            dry_run=False,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
        assert result.unprocessed_archived == 0
        assert _count_raw_projects(db_conn) == 1
        assert _count_raw_archive(db_conn) == 1

    def test_mixed_old_and_new(self, db_conn):
        """混合新旧记录时只处理过期记录。"""
        old = datetime.now(UTC) - timedelta(days=60)
        recent = datetime.now(UTC) - timedelta(days=5)
        _insert_raw_project(db_conn, old)
        _insert_raw_project(db_conn, recent)
        _insert_signal(db_conn, old)
        _insert_signal(db_conn, recent)
        _insert_collection_log(db_conn, old)
        _insert_collection_log(db_conn, recent)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            signals_retention_days=30,
            logs_retention_days=30,
            dry_run=False,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
        assert result.signals_archived == 1
        assert result.logs_deleted == 1
        assert _count_raw_projects(db_conn) == 1
        assert _count_signals(db_conn) == 1
        assert _count_logs(db_conn) == 1
        assert _count_raw_archive(db_conn) == 1
        assert _count_signals_archive(db_conn) == 1

    def test_default_retention_from_settings(self, db_conn, monkeypatch):
        """默认保留期从 settings 读取。"""
        monkeypatch.setattr("app.archive.settings.raw_projects_retention_days", 7)
        monkeypatch.setattr("app.archive.settings.project_signals_retention_days", 7)
        monkeypatch.setattr("app.archive.settings.collection_logs_retention_days", 7)

        old = datetime.now(UTC) - timedelta(days=10)
        _insert_raw_project(db_conn, old)
        _insert_signal(db_conn, old)
        _insert_collection_log(db_conn, old)

        archiver = RawDataArchiver(dry_run=False)
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
        assert result.signals_archived == 1
        assert result.logs_deleted == 1

    def test_result_to_dict(self, db_conn):
        """ArchiveResult.to_dict 输出正确。"""
        archiver = RawDataArchiver(dry_run=True)
        result = archiver.run(db_conn)
        payload = result.to_dict()
        # duration_ms 是真实耗时，值不固定，单独断言
        assert payload.pop("duration_ms") >= 0
        assert payload == {
            "raw_archived": 0,
            "unprocessed_archived": 0,
            "signals_archived": 0,
            "logs_deleted": 0,
            "raw_archive_pruned": 0,
            "signals_archive_pruned": 0,
            "dry_run": True,
        }


# ── 未处理记录的归档（本轮新增的一档）────────────────────────
#
# 起因是实测：库里 693 行 raw_projects 有 509 行（73%）是 processed=0，
# 且它们的 discovery_score 全部 < 0.3（分析阈值），processed=1 的 184 行
# 全部 >= 0.3。低分记录不会立项 → 永远不会被标记已处理 → 永远不满足
# "processed=1 且超期"的归档条件 → 只能无限累积。


class TestUnprocessedArchival:
    """未过分析阈值的采集记录的归档。"""

    def test_expired_unprocessed_is_archived(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=100)
        _insert_raw_project(db_conn, old, processed=0)

        archiver = RawDataArchiver(unprocessed_retention_days=90, dry_run=False)
        result = archiver.run(db_conn)

        assert result.unprocessed_archived == 1
        assert result.raw_archived == 0, "不应被算进已处理那一档"
        assert _count_raw_projects(db_conn) == 0
        assert _count_raw_archive(db_conn) == 1

    def test_unprocessed_is_archived_not_deleted(self, db_conn):
        """搬进归档表而不是直接删 —— 它是复盘「当时为什么没立项」的唯一依据。"""
        old = datetime.now(UTC) - timedelta(days=100)
        raw_id = _insert_raw_project(db_conn, old, processed=0)

        RawDataArchiver(unprocessed_retention_days=90, dry_run=False).run(db_conn)

        row = db_conn.execute(
            "SELECT raw_id, processed, raw_data FROM raw_projects_archive WHERE raw_id = ?",
            (raw_id,),
        ).fetchone()
        assert row is not None, "未处理记录必须能在归档表里找到"
        assert row["processed"] == 0, "归档后仍保留「未处理」这个事实"
        assert row["raw_data"] == '{"name": "Test"}', "原始载荷不得被改写"

    def test_recent_unprocessed_is_kept(self, db_conn):
        recent = datetime.now(UTC) - timedelta(days=10)
        _insert_raw_project(db_conn, recent, processed=0)

        result = RawDataArchiver(unprocessed_retention_days=90, dry_run=False).run(db_conn)

        assert result.unprocessed_archived == 0
        assert _count_raw_projects(db_conn) == 1

    def test_dry_run_counts_unprocessed_without_moving(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=100)
        _insert_raw_project(db_conn, old, processed=0)

        result = RawDataArchiver(unprocessed_retention_days=90, dry_run=True).run(db_conn)

        assert result.unprocessed_archived == 1
        assert _count_raw_projects(db_conn) == 1
        assert _count_raw_archive(db_conn) == 0

    def test_two_tiers_are_independent(self, db_conn):
        """两档保留期各走各的：已处理 30 天、未处理 90 天。"""
        d40 = datetime.now(UTC) - timedelta(days=40)
        d100 = datetime.now(UTC) - timedelta(days=100)
        _insert_raw_project(db_conn, d40, processed=1)  # 已处理、过期 → 归档
        _insert_raw_project(db_conn, d40, processed=0)  # 未处理、未过期 → 留
        _insert_raw_project(db_conn, d100, processed=0)  # 未处理、过期 → 归档

        result = RawDataArchiver(
            raw_retention_days=30,
            unprocessed_retention_days=90,
            dry_run=False,
        ).run(db_conn)

        assert (result.raw_archived, result.unprocessed_archived) == (1, 1)
        assert _count_raw_projects(db_conn) == 1
        assert _count_raw_archive(db_conn) == 2

    def test_unprocessed_retention_defaults_from_settings(self, db_conn, monkeypatch):
        monkeypatch.setattr("app.archive.settings.unprocessed_raw_retention_days", 7)
        old = datetime.now(UTC) - timedelta(days=10)
        _insert_raw_project(db_conn, old, processed=0)

        result = RawDataArchiver(dry_run=False).run(db_conn)

        assert result.unprocessed_archived == 1


# ── 归档表自身的清理 ────────────────────────────────────────
#
# DATABASE_DDL.md §6 早就写了归档表 180/365 天保留期，但此前**零实现** ——
# 归档表只进不出，等于把无界增长从主表搬到了归档表。


class TestArchiveTablePruning:
    """归档表按 archived_at 清理。"""

    @staticmethod
    def _age_archive_rows(conn, table: str, days: int) -> None:
        """把归档表里所有行的 archived_at 往前推 days 天。

        用空格分隔的格式，与 `DEFAULT CURRENT_TIMESTAMP` 的真实写入格式一致 ——
        否则测试自己就在制造格式不一致，测不出真实行为。
        """
        old = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(f"UPDATE {table} SET archived_at = ?", (old,))  # noqa: S608 — 测试内字面量
        conn.commit()

    def test_expired_raw_archive_rows_are_deleted(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        RawDataArchiver(raw_retention_days=30, dry_run=False).run(db_conn)
        assert _count_raw_archive(db_conn) == 1

        self._age_archive_rows(db_conn, "raw_projects_archive", 200)
        result = RawDataArchiver(raw_archive_retention_days=180, dry_run=False).run(db_conn)

        assert result.raw_archive_pruned == 1
        assert _count_raw_archive(db_conn) == 0

    def test_fresh_raw_archive_rows_are_kept(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        RawDataArchiver(raw_retention_days=30, dry_run=False).run(db_conn)

        result = RawDataArchiver(raw_archive_retention_days=180, dry_run=False).run(db_conn)

        assert result.raw_archive_pruned == 0
        assert _count_raw_archive(db_conn) == 1

    def test_expired_signals_archive_rows_are_deleted(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=100)
        _insert_signal(db_conn, old)
        RawDataArchiver(signals_retention_days=90, dry_run=False).run(db_conn)
        assert _count_signals_archive(db_conn) == 1

        self._age_archive_rows(db_conn, "project_signals_archive", 400)
        result = RawDataArchiver(signals_archive_retention_days=365, dry_run=False).run(db_conn)

        assert result.signals_archive_pruned == 1
        assert _count_signals_archive(db_conn) == 0

    def test_dry_run_does_not_prune(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        RawDataArchiver(raw_retention_days=30, dry_run=False).run(db_conn)
        self._age_archive_rows(db_conn, "raw_projects_archive", 200)

        result = RawDataArchiver(raw_archive_retention_days=180, dry_run=True).run(db_conn)

        assert result.raw_archive_pruned == 1, "dry-run 仍应报出会删多少"
        assert _count_raw_archive(db_conn) == 1, "dry-run 不得真删"

    def test_archive_table_retention_defaults_from_settings(self, db_conn, monkeypatch):
        monkeypatch.setattr("app.archive.settings.raw_archive_retention_days", 10)
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        RawDataArchiver(raw_retention_days=30, dry_run=False).run(db_conn)
        self._age_archive_rows(db_conn, "raw_projects_archive", 20)

        result = RawDataArchiver(raw_retention_days=30, dry_run=False).run(db_conn)

        assert result.raw_archive_pruned == 1

    def test_just_archived_row_is_not_immediately_pruned(self, db_conn):
        """同一次运行里刚归档的行不能被当场删掉。

        这条防的是一个**实测出来的真 bug**：`archived_at` 走 SQLite
        `DEFAULT CURRENT_TIMESTAMP`，写成 `'2026-08-22 02:08:51'`（空格分隔），
        而 cutoff 若用 `datetime.isoformat()` 则是 `'...T02:08:51+00:00'`。
        SQLite 里 TIMESTAMP 就是 TEXT，`<` 是字符串比较，空格 0x20 < `T` 0x54 ——
        当天写入的行会被判成"早于 cutoff"。保留期设 0 天时这个错误最明显：
        修复前命中 1 行（刚归档的数据当场被删），修复后 0 行。
        """
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        _insert_signal(db_conn, datetime.now(UTC) - timedelta(days=100))

        result = RawDataArchiver(
            raw_retention_days=30,
            signals_retention_days=90,
            raw_archive_retention_days=0,
            signals_archive_retention_days=0,
            dry_run=False,
        ).run(db_conn)

        assert result.raw_archived == 1
        assert result.signals_archived == 1
        assert result.raw_archive_pruned == 0, "刚归档的行不得在同一次运行里被删"
        assert result.signals_archive_pruned == 0
        assert _count_raw_archive(db_conn) == 1
        assert _count_signals_archive(db_conn) == 1

    def test_cutoff_formats_match_their_columns(self, db_conn):
        """两种 cutoff 格式各自对应各自的列，不能混用。"""
        archiver = RawDataArchiver()
        # 应用层写入的列：ISO 8601，带 T 和时区
        assert "T" in archiver._cutoff(1)
        assert "+00:00" in archiver._cutoff(1)
        # 数据库默认值写入的列：空格分隔，无微秒无时区
        db_default = archiver._cutoff_db_default(1)
        assert "T" not in db_default
        assert "+" not in db_default
        assert db_default[10] == " "


# ── 保留期 0 天必须被当真 ────────────────────────────────────


class TestZeroRetentionIsHonored:
    """显式传 0 天不得被静默换成配置默认值。

    这条来自一次真实的自我更正：构造函数原本写 `days or settings.xxx`，
    于是 `raw_archive_retention_days=0` 被当成"没传"而回退到 180 天，
    让一条本该失败的测试"通过"了，差点掩盖真正的时间戳格式 bug。
    0 是合法取值（立刻清理），运维应急与测试都要用。
    """

    def test_zero_is_not_replaced_by_default(self):
        archiver = RawDataArchiver(
            raw_retention_days=0,
            signals_retention_days=0,
            logs_retention_days=0,
            unprocessed_retention_days=0,
            raw_archive_retention_days=0,
            signals_archive_retention_days=0,
        )
        assert archiver.raw_retention_days == 0
        assert archiver.signals_retention_days == 0
        assert archiver.logs_retention_days == 0
        assert archiver.unprocessed_retention_days == 0
        assert archiver.raw_archive_retention_days == 0
        assert archiver.signals_archive_retention_days == 0

    def test_none_still_falls_back_to_settings(self, monkeypatch):
        monkeypatch.setattr("app.archive.settings.raw_projects_retention_days", 42)
        assert RawDataArchiver().raw_retention_days == 42

    def test_zero_retention_actually_archives_everything(self, db_conn):
        """0 天 = 立刻清理，连刚写入的行也算过期。"""
        _insert_raw_project(db_conn, datetime.now(UTC) - timedelta(seconds=1), processed=1)
        result = RawDataArchiver(raw_retention_days=0, dry_run=False).run(db_conn)
        assert result.raw_archived == 1

    def test_total_affected_sums_every_bucket(self, db_conn):
        result = ArchiveResult(
            raw_archived=1,
            unprocessed_archived=2,
            signals_archived=4,
            logs_deleted=8,
            raw_archive_pruned=16,
            signals_archive_pruned=32,
        )
        assert result.total_affected == 63


# ── 运行历史记录 ────────────────────────────────────────────


class TestRunRecording:
    """run_and_record 把每次运行写入 archive_runs。"""

    def test_successful_run_is_recorded(self, db_conn):
        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)

        archiver = RawDataArchiver(raw_retention_days=30, dry_run=False)
        result = archiver.run_and_record(db_conn, trigger=TRIGGER_MANUAL)

        runs = ArchiveRunRepository(db_conn).list_recent()
        assert len(runs) == 1
        row = runs[0]
        assert row["status"] == STATUS_SUCCESS
        assert row["trigger"] == TRIGGER_MANUAL
        assert row["raw_archived"] == result.raw_archived == 1
        assert row["dry_run"] == 0
        assert row["error_message"] is None

    def test_failed_run_is_also_recorded(self, db_conn):
        """失败必须留痕 —— 否则「归档三天没跑成功」在界面上看不出来。"""
        archiver = RawDataArchiver(dry_run=False)
        boom = RuntimeError("disk on fire")

        def explode(_conn):
            raise boom

        archiver._archive_raw_projects = explode  # type: ignore[method-assign]

        with pytest.raises(RuntimeError, match="disk on fire"):
            archiver.run_and_record(db_conn, trigger=TRIGGER_SCHEDULER)

        runs = ArchiveRunRepository(db_conn).list_recent()
        assert len(runs) == 1
        assert runs[0]["status"] == STATUS_FAILED
        assert runs[0]["trigger"] == TRIGGER_SCHEDULER
        assert "disk on fire" in runs[0]["error_message"]

    def test_record_failure_does_not_mask_archive_result(self, db_conn, monkeypatch):
        """写历史失败时归档结果照样返回 —— 不能因为记账失败就丢掉真实成果。"""

        def broken_record(self, **kwargs):
            raise RuntimeError("history table gone")

        monkeypatch.setattr(ArchiveRunRepository, "record", broken_record)

        old = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old, processed=1)
        result = RawDataArchiver(raw_retention_days=30, dry_run=False).run_and_record(db_conn, trigger=TRIGGER_MANUAL)

        assert result.raw_archived == 1
        assert _count_raw_archive(db_conn) == 1

    def test_dry_run_recorded_as_dry_run(self, db_conn):
        RawDataArchiver(dry_run=True).run_and_record(db_conn, trigger=TRIGGER_MANUAL)
        assert ArchiveRunRepository(db_conn).list_recent()[0]["dry_run"] == 1

    def test_run_with_nothing_to_archive_still_records_a_row(self, db_conn):
        """空转也必须留痕 —— 这条决定了「archive_runs 为 0」该怎么解读。

        2026-08-24 实测线上库 `archive_runs` **0 行**，此前文档把原因写成
        「数据还没超过保留期，所以每次触发都无事可做」。**那个解释是错的。**

        因为空转同样会写一条 `status=success` 的记录，所以 0 行只可能是
        **一次都没被触发过**。两个诊断的处置动作完全不同：
        「无事可做」是"再等等就好"，「从没触发」是"调度那一段从未被验证"。

        这条断言就是那个判据。如果哪天改成"没活干就不记录"，
        `archive_runs = 0` 会重新变成二义的 —— 而它是运维唯一的可观测入口
        （`GET /api/v1/archive/runs` 的 `summary.total_runs`）。
        """
        # 空库，一行都不够老，各分项必然全 0
        result = RawDataArchiver(raw_retention_days=30, dry_run=False).run_and_record(
            db_conn, trigger=TRIGGER_SCHEDULER
        )

        expected_archived = 0
        assert result.raw_archived == expected_archived
        assert result.signals_archived == expected_archived
        assert result.logs_deleted == expected_archived

        runs = ArchiveRunRepository(db_conn).list_recent()
        expected_runs = 1
        assert len(runs) == expected_runs, "空转也必须留下一条记录，否则 archive_runs=0 无法区分「没活干」和「没跑过」"
        assert runs[0]["status"] == STATUS_SUCCESS
        assert runs[0]["raw_archived"] == expected_archived
        assert runs[0]["error_message"] is None

        # 反向：这条记录必须真的能被运维那个入口数到
        assert ArchiveRunRepository(db_conn).counts()["total"] == expected_runs
