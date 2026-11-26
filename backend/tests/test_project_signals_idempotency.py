"""project_signals 幂等写入回归（2026-11-13 审查 P1）。

背景：`persist_collection_result` 对 new/duplicate **无差别** INSERT 信号，
而 twitter_keyword 每 15 分钟一轮、search/recent 窗口重叠 —— 同一条推文在
lookback 窗口内被重复计数，heat_signals 的 COUNT(*) 提前饱和、captured_at
每轮刷新让旧推文持续"新鲜"。

修复契约：
- 带**稳定外部 ID**（tweet_id / post_id / message_id）的信号：同一
  (dedup_key, signal_type, signal_source, external_id) 只落一行
  （唯一索引 + 写入 ON CONFLICT DO NOTHING），首见 captured_at 保留；
- 无外部 ID 的信号（discord 作者级信号等）：照旧逐条追加，不去重 ——
  两条内容相同但作者不同的消息是**不同的**信号；
- init_db 对存量重复行去重（每组保留最新 captured_at 的一行）。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from app.collectors.base import CollectorResult, RawDiscovery, RawSignal
from app.collectors.persistence import CollectionRepository
from app.db import init_db


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _result_with_signal(
    *,
    dedup_name: str,
    signal_type: str,
    external_id: str | None,
    strength: float = 0.6,
) -> CollectorResult:
    signal_data: dict = {"text": "gm", "like_count": 10}
    if external_id is not None:
        signal_data["tweet_id"] = external_id
    item = RawDiscovery(
        source_id="twitter_keyword",
        raw_id=f"raw-{dedup_name}",
        name=dedup_name,
        url=f"https://example.com/{dedup_name}",
        sector="DeFi",
        stage="pre-token",
        raw_data={"origin": "test"},
        raw_signals=[
            RawSignal(
                signal_type=signal_type,
                signal_source="twitter",
                signal_data=signal_data,
                signal_strength=strength,
                captured_at=datetime.now(UTC),
            )
        ],
    )
    result = CollectorResult(source_id="twitter_keyword", items=[item], status="success")
    result.started_at = datetime.now(UTC)
    result.finished_at = datetime.now(UTC)
    return result


def _signal_count(conn: sqlite3.Connection, dedup_key: str) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM project_signals WHERE dedup_key = ?", (dedup_key,)).fetchone()[0])


# ── 唯一约束本体 ────────────────────────────────


def test_init_db_creates_unique_index_on_signal_identity():
    conn = _fresh_conn()
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='ux_project_signals_identity'"
        ).fetchone()
        assert row is not None, "init_db 未创建 ux_project_signals_identity 唯一索引"
    finally:
        conn.close()


def test_init_db_adds_external_id_column():
    conn = _fresh_conn()
    try:
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(project_signals)").fetchall()}
        assert "external_id" in cols
    finally:
        conn.close()


def test_duplicate_signal_direct_insert_is_rejected():
    conn = _fresh_conn()
    try:
        conn.execute(
            """
            INSERT INTO project_signals (signal_id, dedup_key, signal_type, signal_source,
                                         signal_data, external_id)
            VALUES ('sig-1', 'k', 'twitter_mention', 'twitter', '{}', 'tweet-1')
            """
        )
        try:
            conn.execute(
                """
                INSERT INTO project_signals (signal_id, dedup_key, signal_type, signal_source,
                                             signal_data, external_id)
                VALUES ('sig-2', 'k', 'twitter_mention', 'twitter', '{}', 'tweet-1')
                """
            )
            raise AssertionError("同 identity 的第二条信号应被唯一索引拒绝")
        except sqlite3.IntegrityError:
            pass
    finally:
        conn.close()


# ── 写入路径的幂等语义 ──────────────────────────


def test_persist_twice_keeps_one_signal_with_first_captured_at():
    """同一推文两轮采集：只落一行，且保留首见时间（不刷新成"永远新鲜"）。"""
    conn = _fresh_conn()
    try:
        repo = CollectionRepository(conn)
        first = _result_with_signal(dedup_name="Alpha One", signal_type="twitter_mention", external_id="tweet-1")
        repo.persist_collection_result(first)
        second = _result_with_signal(dedup_name="Alpha One", signal_type="twitter_mention", external_id="tweet-1")
        second.items[0].raw_signals[0].captured_at = datetime.now(UTC) + timedelta(hours=1)
        repo.persist_collection_result(second)

        rows = conn.execute("SELECT captured_at FROM project_signals WHERE dedup_key LIKE '%alpha%'").fetchall()
        assert len(rows) == 1, f"同一条推文落了 {len(rows)} 行 —— 热度统计被灌水"
        first_at = first.items[0].raw_signals[0].captured_at.isoformat()
        assert rows[0]["captured_at"].startswith(first_at[:19]), "captured_at 被第二轮刷新，旧推文永远新鲜"
    finally:
        conn.close()


def test_signals_without_external_id_still_append():
    """无外部 ID 的信号（discord 作者级）不去重 —— 相同内容不同来源是不同信号。"""
    conn = _fresh_conn()
    try:
        repo = CollectionRepository(conn)
        r1 = _result_with_signal(dedup_name="Alpha One", signal_type="community_activity", external_id=None)
        r2 = _result_with_signal(dedup_name="Alpha One", signal_type="community_activity", external_id=None)
        repo.persist_collection_result(r1)
        repo.persist_collection_result(r2)

        rows = conn.execute("SELECT signal_data FROM project_signals WHERE dedup_key LIKE '%alpha%'").fetchall()
        assert len(rows) == 2, "无外部 ID 的信号不应被误去重"
    finally:
        conn.close()


def test_different_tweet_ids_stay_separate():
    conn = _fresh_conn()
    try:
        repo = CollectionRepository(conn)
        repo.persist_collection_result(
            _result_with_signal(dedup_name="Alpha One", signal_type="twitter_mention", external_id="tweet-a")
        )
        repo.persist_collection_result(
            _result_with_signal(dedup_name="Alpha One", signal_type="twitter_mention", external_id="tweet-b")
        )
        assert _signal_count(conn, conn.execute("SELECT dedup_key FROM raw_projects LIMIT 1").fetchone()[0]) == 2
    finally:
        conn.close()


# ── 存量库升级路径 ──────────────────────────────


def test_init_db_backfills_external_id_and_dedupes_legacy_rows():
    """模拟存量库：同一推文已经插了两轮 → 保留最新一条，external_id 回填。"""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE project_signals (
            signal_id       TEXT PRIMARY KEY,
            project_id      TEXT,
            dedup_key       TEXT,
            signal_type     TEXT NOT NULL,
            signal_source   TEXT NOT NULL,
            signal_data     TEXT NOT NULL,
            signal_strength REAL DEFAULT 0.0,
            captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    data = json.dumps({"tweet_id": "tweet-9", "text": "gm"})
    conn.execute(
        "INSERT INTO project_signals (signal_id, dedup_key, signal_type, signal_source, signal_data, captured_at)"
        " VALUES ('sig-old', 'k1', 'twitter_mention', 'twitter', ?, '2026-11-13T08:00:00+00:00')",
        (data,),
    )
    conn.execute(
        "INSERT INTO project_signals (signal_id, dedup_key, signal_type, signal_source, signal_data, captured_at)"
        " VALUES ('sig-new', 'k1', 'twitter_mention', 'twitter', ?, '2026-11-13T09:00:00+00:00')",
        (data,),
    )
    conn.commit()

    init_db(conn)

    rows = conn.execute("SELECT signal_id, external_id FROM project_signals").fetchall()
    assert len(rows) == 1, f"存量重复信号未被清理：{[dict(r) for r in rows]}"
    assert rows[0]["signal_id"] == "sig-new", "应保留最新 captured_at 的一行"
    assert rows[0]["external_id"] == "tweet-9", "存量行应回填 external_id"
    conn.close()
