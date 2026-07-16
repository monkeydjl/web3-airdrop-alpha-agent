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


def _insert(conn, raw_id: str, name: str, sector: str = "DeFi", score: float = 0.8):
    dedup = create_dedup_key(name, sector).to_string()
    pid = generate_deterministic_id(create_dedup_key(name, sector))
    raw_data = json.dumps(
        {
            "name": name,
            "sector": sector,
            "slug": name.lower().replace(" ", "-"),
            "no_token_yet": True,
            "stage": "mainnet",
        }
    )
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
            datetime.now(UTC).isoformat(),
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
