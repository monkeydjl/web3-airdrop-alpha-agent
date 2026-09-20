"""Tests for User Profile Memory service (Roadmap §24.3 / §25.5.3 / W12-02)."""

import sqlite3

import pytest

from app.db import init_db
from app.services.user_memory import _CLEARED_USERS, UserProfileMemoryService


@pytest.fixture
def memory_db():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


def test_empty_user_profile(memory_db):
    svc = UserProfileMemoryService(conn=memory_db)
    profile = svc.infer_user_profile("user_fresh_1")

    assert profile.user_id == "user_fresh_1"
    assert profile.sector_affinity == {}
    assert profile.risk_tolerance == "moderate"
    assert profile.favorite_sectors == []
    assert profile.engagement_summary["total_signals"] == 0
    assert not profile.is_cleared


def test_infer_profile_from_actions(memory_db):
    # Seed projects
    memory_db.execute(
        "INSERT INTO projects (id, name, sector, stage, score, label, confidence, risk_json) "
        "VALUES ('proj-ai-1', 'AI Project', 'AI', 'testnet', 80, 'FARM', 0.9, '{\"overall_risk_score\": 20}')"
    )
    memory_db.execute(
        "INSERT INTO projects (id, name, sector, stage, score, label, confidence, risk_json) "
        "VALUES ('proj-defi-1', 'DeFi Project', 'DeFi', 'mainnet', 60, 'WATCH', 0.8, '{\"overall_risk_score\": 75, \"flags\": [\"high_risk\"]}')"
    )
    memory_db.execute(
        "INSERT INTO projects (id, name, sector, stage, score, label, confidence, risk_json) "
        "VALUES ('proj-l2-1', 'L2 Project', 'L2', 'mainnet', 85, 'FARM', 0.95, '{\"overall_risk_score\": 30}')"
    )

    # 1. User loves AI (positive feedback + interaction)
    memory_db.execute(
        "INSERT INTO feedback (project_id, user_id, signal, outcome) VALUES ('proj-ai-1', 'test-user-1', 'useful', 'airdropped')"
    )
    memory_db.execute(
        "INSERT INTO interactions (project_id, user_id, status) VALUES ('proj-ai-1', 'test-user-1', 'active')"
    )

    # 2. User interested in L2 (watchlist)
    memory_db.execute(
        "INSERT INTO watchlist (project_id, user_id) VALUES ('proj-l2-1', 'test-user-1')"
    )

    # 3. User dislikes/avoids high-risk DeFi (skipped + useless feedback)
    memory_db.execute(
        "INSERT INTO project_skips (project_id, user_id) VALUES ('proj-defi-1', 'test-user-1')"
    )
    memory_db.execute(
        "INSERT INTO feedback (project_id, user_id, signal) VALUES ('proj-defi-1', 'test-user-1', 'useless')"
    )
    memory_db.commit()

    svc = UserProfileMemoryService(conn=memory_db)
    profile = svc.infer_user_profile("test-user-1")

    assert profile.user_id == "test-user-1"
    assert profile.engagement_summary["total_signals"] == 5

    # AI affinity should be > 1.0 (positive)
    assert profile.sector_affinity.get("AI", 1.0) > 1.0
    # L2 affinity should be > 1.0 (positive)
    assert profile.sector_affinity.get("L2", 1.0) > 1.0
    # DeFi affinity should be < 1.0 (negative due to skip and useless)
    assert profile.sector_affinity.get("DeFi", 1.0) < 1.0

    assert "AI" in profile.favorite_sectors
    # User avoided the only high risk project -> conservative
    assert profile.risk_tolerance == "conservative"


def test_personalize_projects(memory_db):
    svc = UserProfileMemoryService(conn=memory_db)

    profile = {
        "sector_affinity": {
            "AI": 1.5,
            "DeFi": 0.8,
        }
    }

    projects = [
        {"id": "p-defi", "name": "DeFi Alpha", "sector": "DeFi", "score": 80, "confidence": 0.9},
        {"id": "p-ai", "name": "AI Agent", "sector": "AI", "score": 70, "confidence": 0.9},
    ]

    # Without personalization, DeFi (80) > AI (70)
    # With personalization:
    # AI personalized_score = 70 * 1.5 = 105.0
    # DeFi personalized_score = 80 * 0.8 = 64.0
    # AI should rank first!
    ranked = svc.personalize_projects(projects, profile)

    assert ranked[0]["id"] == "p-ai"
    assert ranked[0]["personalized_score"] == 105.0
    assert ranked[0]["score"] == 70  # Base score untouched!

    assert ranked[1]["id"] == "p-defi"
    assert ranked[1]["personalized_score"] == 64.0
    assert ranked[1]["score"] == 80  # Base score untouched!


def test_clear_user_profile(memory_db):
    uid = "user-to-clear"
    svc = UserProfileMemoryService(conn=memory_db)

    # Seed an action
    memory_db.execute(
        "INSERT INTO watchlist (project_id, user_id) VALUES ('proj-1', ?)", (uid,)
    )
    memory_db.commit()

    prof_before = svc.infer_user_profile(uid)
    assert prof_before.engagement_summary["watchlist_count"] == 1

    svc.clear_user_profile(uid)
    assert uid in _CLEARED_USERS

    prof_after = svc.infer_user_profile(uid)
    assert prof_after.is_cleared
    assert prof_after.sector_affinity == {}
    assert prof_after.engagement_summary["total_signals"] == 0

    # Cleanup global
    _CLEARED_USERS.discard(uid)
