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
from app.db import DbConnection, dict_from_row, get_connection
from app.utils.redact import redact

logger = structlog.get_logger(__name__)


class CollectionRepository:
    """采集数据持久化仓库。"""

    def __init__(self, conn: DbConnection | None = None) -> None:
        self._conn = conn

    def _get_conn(self) -> DbConnection:
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
        """获取未处理且达到初筛分数的原始项目，并带上同一项目的低分佐证记录。

        `discovery_score` 衡量的是"作为独立发现有多值得跟进"，而 coingecko(0.1)、
        etherscan(≤0.28)、cryptorank(≤0.28) 这类**信号补充源**的分数天然低于分析
        阈值 0.3。只按分数过滤会把它们全部挡在门外——于是 coingecko 的
        `token_listed` 永远纠正不了 `no_token_yet`、etherscan 的 `has_contract`
        永远补充不到真实项目上，跨源合并对这三个源等于从不存在。

        正确语义是：一条低分记录**自己**不足以立项，但只要同一 dedup_key 已经有
        记录过线，它就是这个项目的佐证，必须一并进入合并。
        """
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
            rows = [dict(row) for row in cursor.fetchall()]
            if rows:
                rows.extend(self._corroborating_rows(conn, rows, min_discovery_score))
            return rows
        finally:
            if self._should_close():
                conn.close()

    @staticmethod
    def _corroborating_rows(
        conn: Any,
        rows: list[dict[str, Any]],
        min_discovery_score: float,
    ) -> list[dict[str, Any]]:
        """同一 dedup_key 下、分数未过线的其余未处理记录。"""
        keys = sorted({row["dedup_key"] for row in rows if row.get("dedup_key")})
        if not keys:
            return []
        seen_ids = {row["raw_id"] for row in rows}
        extra: list[dict[str, Any]] = []
        # 分块查询：SQLite 默认绑定变量上限 999，一次塞完会在大批量时报错
        for start in range(0, len(keys), 400):
            chunk = keys[start : start + 400]
            placeholders = ",".join("?" for _ in chunk)
            cursor = conn.execute(
                f"""
                SELECT raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score, project_id
                FROM raw_projects
                WHERE processed = 0
                  AND discovery_score < ?
                  AND COALESCE(quarantined, 0) = 0
                  AND dedup_key IN ({placeholders})
                """,  # noqa: S608 — 占位符按数量生成，取值仍走绑定参数
                (min_discovery_score, *chunk),
            )
            for row in cursor.fetchall():
                record = dict(row)
                if record["raw_id"] not in seen_ids:
                    seen_ids.add(record["raw_id"])
                    extra.append(record)
        return extra

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
            return int(cursor.rowcount)
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

    @staticmethod
    def _existing_dedup_keys(conn: Any, items: list[RawDiscovery]) -> set[tuple[str, str]]:
        """一次性查出这些 discovery 中已存在于 raw_projects 的 (source_id, dedup_key)。

        按 source_id 分组并对 dedup_key 分块（避开 SQLite 变量数上限），把
        N 次单行 SELECT 压缩为每组常数级查询。
        """
        by_source: dict[str, set[str]] = {}
        for item in items:
            by_source.setdefault(item.source_id, set()).add(item.dedup_key)

        found: set[tuple[str, str]] = set()
        chunk_size = 400
        for source_id, keys in by_source.items():
            key_list = list(keys)
            for start in range(0, len(key_list), chunk_size):
                chunk = key_list[start : start + chunk_size]
                placeholders = ",".join("?" * len(chunk))
                # 占位符数量由分块长度决定，取值全部参数化
                sql = f"SELECT dedup_key FROM raw_projects WHERE source_id = ? AND dedup_key IN ({placeholders})"  # noqa: S608
                rows = conn.execute(sql, (source_id, *chunk)).fetchall()
                for row in rows:
                    found.add((source_id, dict_from_row(row)["dedup_key"]))
        return found

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
            # 一次性查出本批次已存在的 (source_id, dedup_key)，替代此前"每条一次 SELECT"
            # 的 N+1 模式（一次 DefiLlama 采集 = 100+ 次往返）。
            existing_keys = self._existing_dedup_keys(conn, result.items)

            items_new = 0
            items_duplicate = 0
            for discovery in result.items:
                key = (discovery.source_id, discovery.dedup_key)
                # 批内同 dedup_key 的后续条目也算重复（旧实现依赖同事务内 SELECT
                # 才能看到，这里显式记账，语义一致且不再需要额外查询）。
                existing = key in existing_keys

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
                    existing_keys.add(key)
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
                    redact(result.error_message) if result.error_message else None,
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
