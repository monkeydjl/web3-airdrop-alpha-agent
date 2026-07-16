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

from app.archive import RawDataArchiver
from app.db import init_db


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

    def test_only_processed_raw_projects_archived(self, db_conn):
        """未处理的 raw_projects 不被归档。"""
        old_processed = datetime.now(UTC) - timedelta(days=40)
        old_unprocessed = datetime.now(UTC) - timedelta(days=40)
        _insert_raw_project(db_conn, old_processed, processed=1)
        _insert_raw_project(db_conn, old_unprocessed, processed=0)

        archiver = RawDataArchiver(
            raw_retention_days=30,
            dry_run=False,
        )
        result = archiver.run(db_conn)

        assert result.raw_archived == 1
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
        assert result.to_dict() == {
            "raw_archived": 0,
            "signals_archived": 0,
            "logs_deleted": 0,
            "dry_run": True,
        }
