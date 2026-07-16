"""Collector Persistence.

把采集结果写入数据库，并管理 raw_projects → projects 的流转。

参考：
- DATABASE_DDL.md §2.13-2.19
- DATA_SOURCE_STRATEGY.md §采集管道
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import structlog

from app.collectors.base import CollectorResult, RawDiscovery
from app.db import get_connection

logger = structlog.get_logger(__name__)


class CollectionRepository:
    """采集数据持久化仓库。"""

    def __init__(self, conn=None):
        self._conn = conn

    def _get_conn(self):
        return self._conn if self._conn else get_connection()

    def _should_close(self) -> bool:
        return self._conn is None

    def ensure_source(self, source_id: str, source_type: str, source_name: str) -> None:
        """幂等注册数据源。"""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO data_sources (source_id, source_type, source_name)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_name = excluded.source_name,
                    updated_at = datetime('now')
                """,
                (source_id, source_type, source_name),
            )
            conn.commit()
        finally:
            if self._should_close():
                conn.close()

    def save_collection_result(self, result: CollectorResult) -> None:
        """保存采集日志。"""
        conn = self._get_conn()
        try:
            conn.execute(
                """
                INSERT INTO collection_logs (
                    log_id, source_id, started_at, finished_at,
                    items_collected, items_new, items_duplicate,
                    status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    result.source_id,
                    result.started_at.isoformat() if result.started_at else None,
                    result.finished_at.isoformat() if result.finished_at else None,
                    len(result.items),
                    result.items_new,
                    result.items_duplicate,
                    result.status,
                    result.error_message,
                ),
            )
            conn.commit()
        finally:
            if self._should_close():
                conn.close()

    def save_raw_discovery(self, discovery: RawDiscovery) -> bool:
        """保存一条原始发现记录。

        返回 True 表示新记录（dedup_key 在当前源中未存在），False 表示已存在。
        """
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                "SELECT raw_id FROM raw_projects WHERE source_id = ? AND dedup_key = ?",
                (discovery.source_id, discovery.dedup_key),
            )
            existing = cursor.fetchone()

            raw_data = discovery.raw_data.copy()
            raw_data["name"] = discovery.name
            raw_data["url"] = discovery.url
            raw_data["sector"] = discovery.sector
            raw_data["stage"] = discovery.stage
            raw_data["discovery_score"] = discovery.discovery_score

            if existing:
                # 更新已有记录（心跳 + 分数变化）
                conn.execute(
                    """
                    UPDATE raw_projects
                    SET raw_data = ?, discovery_score = ?, discovered_at = ?, project_id = ?
                    WHERE source_id = ? AND dedup_key = ?
                    """,
                    (
                        json.dumps(raw_data, default=str),
                        discovery.discovery_score,
                        discovery.discovered_at.isoformat(),
                        discovery.project_id,
                        discovery.source_id,
                        discovery.dedup_key,
                    ),
                )
                conn.commit()
                return False

            raw_id = uuid.uuid4().hex
            conn.execute(
                """
                INSERT INTO raw_projects (
                    raw_id, source_id, dedup_key, raw_data, discovered_at,
                    processed, discovery_score, project_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    raw_id,
                    discovery.source_id,
                    discovery.dedup_key,
                    json.dumps(raw_data, default=str),
                    discovery.discovered_at.isoformat(),
                    0,
                    discovery.discovery_score,
                    discovery.project_id,
                ),
            )
            conn.commit()
            return True
        finally:
            if self._should_close():
                conn.close()

    def save_raw_signals(self, discovery: RawDiscovery) -> None:
        """保存原始信号到 project_signals 表。"""
        if not discovery.raw_signals:
            return

        conn = self._get_conn()
        try:
            for signal in discovery.raw_signals:
                conn.execute(
                    """
                    INSERT INTO project_signals (
                        signal_id, project_id, dedup_key, signal_type,
                        signal_source, signal_data, signal_strength, captured_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid.uuid4().hex,
                        discovery.project_id,
                        discovery.dedup_key,
                        signal.signal_type,
                        signal.signal_source,
                        json.dumps(signal.signal_data, default=str),
                        signal.signal_strength,
                        signal.captured_at.isoformat(),
                    ),
                )
            conn.commit()
        finally:
            if self._should_close():
                conn.close()

    def get_unprocessed_raw_projects(
        self,
        min_discovery_score: float = 0.3,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取未处理且达到初筛分数的原始项目。"""
        conn = self._get_conn()
        try:
            cursor = conn.execute(
                """
                SELECT raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id
                FROM raw_projects
                WHERE processed = 0
                  AND discovery_score >= ?
                  AND COALESCE(quarantined, 0) = 0
                ORDER BY discovery_score DESC, discovered_at DESC
                LIMIT ?
                """,
                (min_discovery_score, limit),
            )
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            if self._should_close():
                conn.close()

    def mark_raw_project_processed(
        self,
        raw_id: str | None = None,
        project_id: str | None = None,
        dedup_key: str | None = None,
    ) -> int:
        """标记原始项目已处理。

        至少提供 raw_id / project_id / dedup_key 之一。
        返回受影响行数。
        """
        if not raw_id and not project_id and not dedup_key:
            raise ValueError("Either raw_id, project_id, or dedup_key must be provided")

        conn = self._get_conn()
        try:
            if raw_id:
                cursor = conn.execute(
                    """
                    UPDATE raw_projects
                    SET processed = 1, processed_at = datetime('now'),
                        project_id = COALESCE(?, project_id)
                    WHERE raw_id = ?
                    """,
                    (project_id, raw_id),
                )
            elif dedup_key:
                cursor = conn.execute(
                    """
                    UPDATE raw_projects
                    SET processed = 1, processed_at = datetime('now'),
                        project_id = COALESCE(?, project_id)
                    WHERE dedup_key = ?
                    """,
                    (project_id, dedup_key),
                )
            else:
                cursor = conn.execute(
                    """
                    UPDATE raw_projects
                    SET processed = 1, processed_at = datetime('now'), project_id = ?
                    WHERE project_id = ?
                    """,
                    (project_id, project_id),
                )
            conn.commit()
            return cursor.rowcount
        finally:
            if self._should_close():
                conn.close()

    def update_source_sync_status(
        self,
        source_id: str,
        status: str,
        api_calls_today: int | None = None,
    ) -> None:
        """更新数据源同步状态。"""
        conn = self._get_conn()
        try:
            if api_calls_today is not None:
                conn.execute(
                    """
                    UPDATE data_sources
                    SET sync_status = ?, last_sync = datetime('now'),
                        api_calls_today = ?, updated_at = datetime('now')
                    WHERE source_id = ?
                    """,
                    (status, api_calls_today, source_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE data_sources
                    SET sync_status = ?, last_sync = datetime('now'),
                        updated_at = datetime('now')
                    WHERE source_id = ?
                    """,
                    (status, source_id),
                )
            conn.commit()
        finally:
            if self._should_close():
                conn.close()

    def persist_collection_result(
        self,
        result: CollectorResult,
        source_type: str = "api",
        source_name: str = "",
    ) -> None:
        """Persist one collection run end-to-end with a single transaction.

        Writes data source, raw discoveries, signals, collection log, and sync status.
        Uses a single connection and one transaction to avoid per-record overhead.
        Also computes and sets items_new / items_duplicate.
        """
        conn = self._get_conn()
        try:
            # 1. 确保数据源已注册
            conn.execute(
                """
                INSERT INTO data_sources (source_id, source_type, source_name)
                VALUES (?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                    source_type = excluded.source_type,
                    source_name = excluded.source_name,
                    updated_at = datetime('now')
                """,
                (result.source_id, source_type, source_name or result.source_id),
            )

            # 2. 批量写入原始发现及其信号
            items_new = 0
            items_duplicate = 0
            for discovery in result.items:
                existing = conn.execute(
                    "SELECT raw_id FROM raw_projects WHERE source_id = ? AND dedup_key = ?",
                    (discovery.source_id, discovery.dedup_key),
                ).fetchone()

                raw_data = discovery.raw_data.copy()
                raw_data["name"] = discovery.name
                raw_data["url"] = discovery.url
                raw_data["sector"] = discovery.sector
                raw_data["stage"] = discovery.stage
                raw_data["discovery_score"] = discovery.discovery_score

                if existing:
                    conn.execute(
                        """
                        UPDATE raw_projects
                        SET raw_data = ?, discovery_score = ?, discovered_at = ?, project_id = ?
                        WHERE source_id = ? AND dedup_key = ?
                        """,
                        (
                            json.dumps(raw_data, default=str),
                            discovery.discovery_score,
                            discovery.discovered_at.isoformat(),
                            discovery.project_id,
                            discovery.source_id,
                            discovery.dedup_key,
                        ),
                    )
                    items_duplicate += 1
                else:
                    raw_id = uuid.uuid4().hex
                    conn.execute(
                        """
                        INSERT INTO raw_projects (
                            raw_id, source_id, dedup_key, raw_data, discovered_at,
                            processed, discovery_score, project_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            raw_id,
                            discovery.source_id,
                            discovery.dedup_key,
                            json.dumps(raw_data, default=str),
                            discovery.discovered_at.isoformat(),
                            0,
                            discovery.discovery_score,
                            discovery.project_id,
                        ),
                    )
                    items_new += 1

                # 写入信号
                if discovery.raw_signals:
                    for signal in discovery.raw_signals:
                        conn.execute(
                            """
                            INSERT INTO project_signals (
                                signal_id, project_id, dedup_key, signal_type,
                                signal_source, signal_data, signal_strength, captured_at
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            (
                                uuid.uuid4().hex,
                                discovery.project_id,
                                discovery.dedup_key,
                                signal.signal_type,
                                signal.signal_source,
                                json.dumps(signal.signal_data, default=str),
                                signal.signal_strength,
                                signal.captured_at.isoformat(),
                            ),
                        )

            result.items_new = items_new
            result.items_duplicate = items_duplicate

            # 3. 采集日志
            conn.execute(
                """
                INSERT INTO collection_logs (
                    log_id, source_id, started_at, finished_at,
                    items_collected, items_new, items_duplicate,
                    status, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    result.source_id,
                    result.started_at.isoformat() if result.started_at else None,
                    result.finished_at.isoformat() if result.finished_at else None,
                    len(result.items),
                    items_new,
                    items_duplicate,
                    result.status,
                    result.error_message,
                ),
            )

            # 4. 同步状态
            conn.execute(
                """
                UPDATE data_sources
                SET sync_status = ?, last_sync = datetime('now'), updated_at = datetime('now')
                WHERE source_id = ?
                """,
                (result.status, result.source_id),
            )

            conn.commit()
        finally:
            if self._should_close():
                conn.close()
