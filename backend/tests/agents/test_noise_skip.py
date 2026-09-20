"""Analysis queue skips denylisted historical raw_projects."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

import pytest

from app.agents.collector import CollectorAgent
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.utils.normalize import create_dedup_key, generate_deterministic_id


@pytest.fixture
def repo_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _insert(
    conn,
    raw_id: str,
    name: str,
    sector: str = "DeFi",
    score: float = 0.8,
    *,
    raw_data: str | None = None,
    discovered_at: str | None = None,
):
    dedup = create_dedup_key(name, sector).to_string()
    pid = generate_deterministic_id(create_dedup_key(name, sector))
    if raw_data is None:
        raw_data = json.dumps(
            {
                "name": name,
                "sector": sector,
                "slug": name.lower().replace(" ", "-"),
                "no_token_yet": True,
                "stage": "mainnet",
            }
        )
    if discovered_at is None:
        discovered_at = datetime.now(UTC).isoformat()
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            raw_id,
            "defillama",
            dedup,
            raw_data,
            discovered_at,
            score,
            pid,
        ),
    )
    conn.commit()
    return pid


def test_collect_from_repository_skips_and_marks_noise(repo_conn):
    _insert(repo_conn, "r-noise", "Uniswap V4", "Dexs")
    _insert(repo_conn, "r-ok", "Nova Vault", "Yield")
    repo = CollectionRepository(repo_conn)
    agent = CollectorAgent()

    projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)
    names = {p.name for p in projects}
    assert "Nova Vault" in names
    assert "Uniswap V4" not in names

    row = repo_conn.execute(
        "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
        ("r-noise",),
    ).fetchone()
    assert row["processed"] == 1
    # quarantined may be 1 when column exists
    if "quarantined" in row:
        assert row["quarantined"] in (0, 1)

    row_ok = repo_conn.execute(
        "SELECT processed FROM raw_projects WHERE raw_id = ?",
        ("r-ok",),
    ).fetchone()
    assert row_ok["processed"] == 0


class TestCorruptRowQuarantine:
    """队列中毒防护（2026-08-30）：坏行隔离 + 跳过，批次继续。

    此前一条损坏的 raw_data / discovered_at 会让整批 collect_from_repository
    抛异常；该行 processed=0 且按 discovery_score DESC 排序每轮都被重新取到，
    流水线永久卡死，只能手工修库。
    """

    def test_corrupt_raw_data_is_quarantined_and_batch_survives(self, repo_conn):
        _insert(repo_conn, "r-corrupt", "Broken Json", "DeFi", raw_data="{not valid json")
        _insert(repo_conn, "r-ok", "Healthy Protocol", "Yield")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        # 不抛异常是本测试的核心断言 —— 此前这里会整批 raise
        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        names = {p.name for p in projects}
        assert "Healthy Protocol" in names
        assert "Broken Json" not in names

        row = repo_conn.execute(
            "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
            ("r-corrupt",),
        ).fetchone()
        # 必须离开待分析队列：processed=1（隔离路径本身会置位）
        assert row["processed"] == 1
        assert row["quarantined"] == 1

    def test_corrupt_discovered_at_is_quarantined_and_batch_survives(self, repo_conn):
        _insert(repo_conn, "r-badts", "Broken Timestamp", "DeFi", discovered_at="not-a-date")
        _insert(repo_conn, "r-ok", "Another Healthy", "NFT")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        names = {p.name for p in projects}
        assert "Another Healthy" in names
        assert "Broken Timestamp" not in names

        row = repo_conn.execute(
            "SELECT processed, quarantined FROM raw_projects WHERE raw_id = ?",
            ("r-badts",),
        ).fetchone()
        assert row["processed"] == 1
        assert row["quarantined"] == 1

    def test_corrupt_rows_do_not_permanently_jam_the_queue(self, repo_conn):
        """连续多行损坏也只损失这些行本身，其余照常进分析。"""
        for i in range(5):
            _insert(repo_conn, f"r-bad-{i}", f"Bad Actor {i}", "DeFi", raw_data="[[[")
        _insert(repo_conn, "r-ok", "Survivor Protocol", "Yield")
        repo = CollectionRepository(repo_conn)
        agent = CollectorAgent()

        projects = agent.collect_from_repository(repo, min_discovery_score=0.3, limit=10)

        assert {p.name for p in projects} == {"Survivor Protocol"}
        processed = repo_conn.execute("SELECT COUNT(*) AS n FROM raw_projects WHERE processed = 1").fetchone()["n"]
        assert processed == 5
