"""Unit tests for multi-source signal correlation & consensus engine."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.services.signal_correlation import (
    batch_correlate_signals,
    calculate_consensus,
    correlate_signals_for_project,
)


def test_calculate_consensus_empty() -> None:
    res = calculate_consensus([])
    assert res["source_count"] == 0
    assert res["sources"] == []
    assert res["consensus_tier"] == "none"
    assert res["free_alpha_boost"] == 0.0
    assert res["has_testnet_consensus"] is False


def test_calculate_consensus_single_source() -> None:
    signals = [
        {"signal_source": "telegram", "signal_type": "community_activity"},
        {"signal_source": "telegram", "signal_type": "discussion"},
    ]
    res = calculate_consensus(signals)
    assert res["source_count"] == 1
    assert res["sources"] == ["telegram"]
    assert res["consensus_tier"] == "single"
    assert res["consensus_tier_zh"] == "单源情报"
    assert res["free_alpha_boost"] == 0.02
    assert res["has_testnet_consensus"] is False


def test_calculate_consensus_dual_source_with_testnet() -> None:
    signals = [
        {"signal_source": "telegram", "signal_type": "testnet"},
        {"signal_source": "farcaster", "signal_type": "testnet"},
    ]
    res = calculate_consensus(signals)
    assert res["source_count"] == 2
    assert res["sources"] == ["farcaster", "telegram"]
    assert res["consensus_tier"] == "medium"
    assert res["consensus_tier_zh"] == "双源交叉印证"
    assert res["free_alpha_boost"] == 0.08
    assert res["has_testnet_consensus"] is True


def test_calculate_consensus_multi_source() -> None:
    signals = [
        {"signal_source": "telegram", "signal_type": "community_activity"},
        {"signal_source": "farcaster", "signal_type": "discussion"},
        {"signal_source": "github", "signal_type": "code_activity"},
    ]
    res = calculate_consensus(signals)
    assert res["source_count"] == 3
    assert res["consensus_tier"] == "high"
    assert res["consensus_tier_zh"] == "多源高度共识"
    assert res["free_alpha_boost"] == 0.15


def test_db_correlate_signals(tmp_path: pytest.TempPathFactory) -> None:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE project_signals (
            signal_id TEXT PRIMARY KEY,
            project_id TEXT,
            dedup_key TEXT,
            signal_type TEXT NOT NULL,
            signal_source TEXT NOT NULL,
            signal_data TEXT NOT NULL,
            signal_strength REAL DEFAULT 0.0,
            captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    now = datetime.now(UTC).isoformat()
    old = (datetime.now(UTC) - timedelta(days=30)).isoformat()

    conn.execute(
        "INSERT INTO project_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s1", "proj-1", "k1", "testnet", "telegram", "{}", 0.5, now),
    )
    conn.execute(
        "INSERT INTO project_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s2", "proj-1", "k2", "testnet", "farcaster", "{}", 0.5, now),
    )
    # Stale signal outside 14 days
    conn.execute(
        "INSERT INTO project_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s3", "proj-1", "k3", "funding", "github", "{}", 0.5, old),
    )
    conn.execute(
        "INSERT INTO project_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        ("s4", "proj-2", "k4", "airdrop", "telegram", "{}", 0.5, now),
    )
    conn.commit()

    # Test single project correlation
    res1 = correlate_signals_for_project(conn, "proj-1", window_days=14)
    assert res1["source_count"] == 2
    assert res1["consensus_tier"] == "medium"
    assert res1["has_testnet_consensus"] is True

    # Test batch correlation
    batch = batch_correlate_signals(conn, window_days=14)
    assert "proj-1" in batch
    assert "proj-2" in batch
    assert batch["proj-1"]["source_count"] == 2
    assert batch["proj-2"]["source_count"] == 1

    conn.close()
