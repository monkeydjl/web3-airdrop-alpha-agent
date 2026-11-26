"""raw_projects (source_id, dedup_key) 唯一约束回归（2026-11-13 审查 P1）。

此前去重幂等只靠"先 SELECT 后 INSERT"：定时采集（不 claim_run 占锁，
app/scheduler.py）与手动触发（claim_run，routers/v1/collections.py）可在
同一源上并发，各自在 to_thread 里用独立连接持久化 —— 同一 dedup_key 会
插出两行，后续按 dedup_key 的合并、processed 出队标记、热度统计全部失真。

修复后的契约：
- init_db 先清存量重复（每组保留一行：优先 processed=1，否则最早一行），
  再建 UNIQUE(source_id, dedup_key)；
- 直接 INSERT 重复键被数据库拒绝（IntegrityError），不再静默出重；
- persist_collection_result / save_raw_discovery 用 ON CONFLICT 合并，
  跨连接竞态从"数据失真"降级为"被数据库合并"。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.collectors.base import CollectorResult, RawDiscovery
from app.collectors.persistence import CollectionRepository
from app.db import init_db


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _raw_discovery(source_id: str, name: str, score: float = 0.5) -> RawDiscovery:
    return RawDiscovery(
        source_id=source_id,
        raw_id=f"raw-{name}",
        name=name,
        url=f"https://example.com/{name}",
        sector="DeFi",
        stage="pre-token",
        raw_data={"origin": "test"},
        discovery_score=score,
    )


def _collector_result(source_id: str, name: str, score: float = 0.5) -> CollectorResult:
    result = CollectorResult(source_id=source_id, items=[_raw_discovery(source_id, name, score)], status="success")
    result.started_at = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    result.finished_at = datetime(2026, 11, 13, 12, 1, tzinfo=UTC)
    return result


# ── 唯一约束本体 ────────────────────────────────


def test_init_db_creates_unique_index_on_source_and_dedup_key():
    conn = _fresh_conn()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ux_raw_projects_source_dedup'"
        ).fetchone()
        assert row is not None, "init_db 未创建 ux_raw_projects_source_dedup 唯一索引"
    finally:
        conn.close()


def test_duplicate_direct_insert_is_rejected_by_database():
    conn = _fresh_conn()
    try:
        conn.execute(
            """
            INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data)
            VALUES ('raw-a', 'defillama', 'dup-key', '{}')
            """
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data)
                VALUES ('raw-b', 'defillama', 'dup-key', '{}')
                """
            )
    finally:
        conn.close()


# ── 存量库升级路径（老库已有重复行）──────────────


def test_init_db_dedupes_legacy_duplicates_and_keeps_processed_row():
    """模拟唯一索引之前的存量库：同键三行，其中一行已处理。

    init_db 必须先清重再建索引（CREATE UNIQUE INDEX 遇重复行会直接失败），
    且保留 processed=1 的那一行 —— 丢了出队状态，重复采集历史会把已分析
    的项目重新塞回队列。
    """
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE raw_projects (
            raw_id          TEXT PRIMARY KEY,
            source_id       TEXT NOT NULL,
            dedup_key       TEXT NOT NULL,
            raw_data        TEXT NOT NULL,
            discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed       INTEGER DEFAULT 0,
            processed_at    TIMESTAMP,
            project_id      TEXT,
            discovery_score REAL DEFAULT 0.0,
            quarantined     INTEGER DEFAULT 0,
            quarantine_reason TEXT
        )
        """
    )
    for raw_id, processed in (("raw-old-1", 0), ("raw-old-2", 1), ("raw-old-3", 0)):
        conn.execute(
            "INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, processed) VALUES (?, ?, ?, ?, ?)",
            (raw_id, "defillama", "legacy-key", "{}", processed),
        )
    conn.commit()

    init_db(conn)

    rows = conn.execute(
        "SELECT raw_id, processed FROM raw_projects WHERE source_id='defillama' AND dedup_key='legacy-key'"
    ).fetchall()
    assert len(rows) == 1, f"存量重复行未被清理：{[dict(r) for r in rows]}"
    assert rows[0]["raw_id"] == "raw-old-2", "应保留 processed=1 的行（出队状态不能丢）"
    assert rows[0]["processed"] == 1
    # 索引照常建立
    idx = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name='ux_raw_projects_source_dedup'"
    ).fetchone()
    assert idx is not None
    conn.close()


def test_init_db_is_idempotent_after_dedupe():
    """第二次 init_db 在干净库上必须仍是 no-op（可重复启动）。"""
    conn = _fresh_conn()
    try:
        init_db(conn)  # 不抛即通过
        count = conn.execute("SELECT COUNT(*) FROM raw_projects").fetchone()[0]
        assert count == 0
    finally:
        conn.close()


# ── 写入路径的合并语义 ──────────────────────────


def test_persist_collection_result_second_round_counts_duplicate():
    conn = _fresh_conn()
    try:
        repo = CollectionRepository(conn)
        repo.persist_collection_result(_collector_result("defillama", "Alpha One", 0.6))
        result2 = _collector_result("defillama", "Alpha One", 0.7)
        repo.persist_collection_result(result2)

        assert result2.items_new == 0
        assert result2.items_duplicate == 1
        rows = conn.execute("SELECT raw_id, discovery_score FROM raw_projects").fetchall()
        assert len(rows) == 1, "同键二次采集不得产生第二行"
        assert rows[0]["discovery_score"] == 0.7, "重复键应合并更新最新分数"
    finally:
        conn.close()


def test_save_raw_discovery_duplicate_returns_false_and_updates():
    conn = _fresh_conn()
    try:
        repo = CollectionRepository(conn)
        first = _raw_discovery("defillama", "Beta One", 0.4)
        second = _raw_discovery("defillama", "Beta One", 0.9)

        assert repo.save_raw_discovery(first) is True
        assert repo.save_raw_discovery(second) is False

        rows = conn.execute("SELECT raw_id, raw_data FROM raw_projects WHERE source_id='defillama'").fetchall()
        assert len(rows) == 1
        assert json.loads(rows[0]["raw_data"])["discovery_score"] == 0.9
    finally:
        conn.close()
