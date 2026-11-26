from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

from app.services.source_scorecard import fetch_source_scorecards


def _make_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE raw_projects (
            raw_id TEXT PRIMARY KEY,
            source_id TEXT,
            quarantined INTEGER DEFAULT 0,
            processed INTEGER DEFAULT 0,
            discovery_score REAL,
            discovered_at TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE data_sources (
            source_id TEXT PRIMARY KEY,
            sync_status TEXT,
            last_sync TIMESTAMP
        )
        """
    )
    return conn


def _insert_raw(
    conn: sqlite3.Connection, source_id: str, index: int, *, score: float, processed: bool, quarantined: bool = False
) -> None:
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, quarantined, processed, discovery_score, discovered_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            f"{source_id}-{index}",
            source_id,
            1 if quarantined else 0,
            1 if processed else 0,
            score,
            "2026-10-30 08:00:00",
        ),
    )


def test_empty_source_ids_returns_empty() -> None:
    conn = _make_db()
    assert fetch_source_scorecards(conn, []) == {}


def test_scorecards_use_real_metrics_and_verdicts() -> None:
    conn = _make_db()
    now = datetime(2026, 10, 30, 12, tzinfo=UTC)

    # 健康源：4 条，3 条已分析，无隔离
    for i, score in enumerate([0.8, 0.7, 0.6, 0.2]):
        _insert_raw(conn, "defillama", i, score=score, processed=i < 3)

    # 低信号源：20 条全部低于阈值，且未进入分析
    for i in range(20):
        _insert_raw(conn, "medium", i, score=0.05 + i / 1000, processed=False)

    # 高噪声源：4 条中 2 条被隔离
    for i in range(4):
        _insert_raw(conn, "rootdata", i, score=0.4, processed=True, quarantined=i < 2)

    # 断流源：唯一记录 10 天前同步
    _insert_raw(conn, "stale-source", 0, score=0.5, processed=True)

    # 失败源：同步状态 error
    _insert_raw(conn, "failing-source", 0, score=0.5, processed=True)

    conn.executemany(
        "INSERT INTO data_sources (source_id, sync_status, last_sync) VALUES (?, ?, ?)",
        [
            ("defillama", "success", "2026-10-30 11:00:00"),
            ("medium", "success", "2026-10-30 11:00:00"),
            ("rootdata", "success", "2026-10-30 11:00:00"),
            ("stale-source", "success", (now - timedelta(days=10)).isoformat()),
            ("failing-source", "error", "2026-10-30 11:00:00"),
        ],
    )
    conn.commit()

    cards = fetch_source_scorecards(
        conn,
        ["defillama", "medium", "rootdata", "stale-source", "failing-source", "missing"],
        now=now,
    )

    assert cards["defillama"]["total_raw"] == 4
    assert cards["defillama"]["analyzed"] == 3
    assert cards["defillama"]["avg_discovery_score"] == 0.575
    assert cards["defillama"]["verdict"] == "healthy"

    assert cards["medium"]["total_raw"] == 20
    assert cards["medium"]["analysis_rate"] == 0.0
    assert cards["medium"]["verdict"] == "low_signal"

    assert cards["rootdata"]["quarantined"] == 2
    assert cards["rootdata"]["quarantine_rate"] == 0.5
    assert cards["rootdata"]["verdict"] == "noisy"

    assert cards["stale-source"]["freshness_hours"] == 24 * 10
    assert cards["stale-source"]["verdict"] == "stale"

    assert cards["failing-source"]["verdict"] == "failing"

    assert cards["missing"]["total_raw"] == 0
    assert cards["missing"]["verdict"] == "idle"


def test_signal_threshold_is_configurable() -> None:
    conn = _make_db()
    for i, score in enumerate([0.2, 0.35, 0.55, 0.75]):
        _insert_raw(conn, "source", i, score=score, processed=True)
    conn.commit()

    default_cards = fetch_source_scorecards(conn, ["source"])
    assert default_cards["source"]["high_signal"] == 3

    strict_cards = fetch_source_scorecards(conn, ["source"], signal_threshold=0.5)
    assert strict_cards["source"]["high_signal"] == 2

    loose_cards = fetch_source_scorecards(conn, ["source"], signal_threshold=0.2)
    assert loose_cards["source"]["high_signal"] == 4
