"""Unit tests for LeaderElector service (W12-03, ADR-005)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import pytest

from app.config import settings
from app.db import get_connection, init_db
from app.services.leader_election import LeaderElector


@pytest.fixture(autouse=True)
def clean_ha_db(tmp_path, monkeypatch):
    test_db = str(tmp_path / "ha_test.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    init_db()

    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.commit()

    yield

    with get_connection() as conn:
        conn.execute("DELETE FROM leader_election")
        conn.commit()


def test_initial_acquire_and_renew():
    """Initial instance successfully acquires leadership and renews lease."""
    elector = LeaderElector(
        get_connection,
        instance_id="inst_1",
        lease_ttl_seconds=10,
        enabled=True,
    )

    # 1. Initial acquire
    assert elector.acquire_or_renew() is True

    status = elector.get_status()
    assert status["is_leader"] is False  # not updated until _tick, but DB has lease
    assert status["current_leader"] == "inst_1"
    assert status["version"] == 1

    # 2. Renew lease
    assert elector.acquire_or_renew() is True
    status = elector.get_status()
    assert status["current_leader"] == "inst_1"
    assert status["version"] == 2


def test_competing_instances_mutual_exclusion():
    """Second instance cannot acquire lease while first instance lease is active."""
    elector_1 = LeaderElector(
        get_connection,
        instance_id="inst_1",
        lease_ttl_seconds=30,
        enabled=True,
    )
    elector_2 = LeaderElector(
        get_connection,
        instance_id="inst_2",
        lease_ttl_seconds=30,
        enabled=True,
    )

    # Instance 1 acquires
    assert elector_1.acquire_or_renew() is True

    # Instance 2 attempts to acquire -> rejected
    assert elector_2.acquire_or_renew() is False

    status = elector_2.get_status()
    assert status["current_leader"] == "inst_1"


def test_failover_after_lease_expiry():
    """Second instance takes over after first instance's lease expires."""
    elector_1 = LeaderElector(
        get_connection,
        instance_id="inst_1",
        lease_ttl_seconds=2,
        enabled=True,
    )
    elector_2 = LeaderElector(
        get_connection,
        instance_id="inst_2",
        lease_ttl_seconds=10,
        enabled=True,
    )

    assert elector_1.acquire_or_renew() is True
    assert elector_2.acquire_or_renew() is False

    # Simulate lease expiry by updating lease_expires_at in DB to 5 seconds ago
    past = datetime.now(UTC) - timedelta(seconds=5)
    with get_connection() as conn:
        conn.execute(
            "UPDATE leader_election SET lease_expires_at = ? WHERE resource_id = ?",
            (past, "unified_scheduler"),
        )
        conn.commit()

    # Now instance 2 attempts to acquire -> succeeds
    assert elector_2.acquire_or_renew() is True

    status = elector_2.get_status()
    assert status["current_leader"] == "inst_2"
    assert status["version"] >= 2


def test_graceful_step_down():
    """When leader steps down, lease is expired and second instance takes over immediately."""
    elector_1 = LeaderElector(
        get_connection,
        instance_id="inst_1",
        lease_ttl_seconds=60,
        enabled=True,
    )
    elector_2 = LeaderElector(
        get_connection,
        instance_id="inst_2",
        lease_ttl_seconds=60,
        enabled=True,
    )

    assert elector_1.acquire_or_renew() is True
    elector_1._is_leader = True

    # Elector 1 steps down
    assert elector_1.step_down() is True
    assert elector_1.is_leader is False

    # Elector 2 can now acquire immediately
    assert elector_2.acquire_or_renew() is True
    assert elector_2.get_status()["current_leader"] == "inst_2"


@pytest.mark.asyncio
async def test_async_election_lifecycle_and_callbacks():
    """Test background loop promotion and demotion callbacks."""
    promoted_1 = False
    demoted_1 = False
    promoted_2 = False

    def on_p1():
        nonlocal promoted_1
        promoted_1 = True

    def on_d1():
        nonlocal demoted_1
        demoted_1 = True

    def on_p2():
        nonlocal promoted_2
        promoted_2 = True

    elector_1 = LeaderElector(
        get_connection,
        instance_id="inst_1",
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=1,
        on_promoted=on_p1,
        on_demoted=on_d1,
        enabled=True,
    )

    elector_2 = LeaderElector(
        get_connection,
        instance_id="inst_2",
        lease_ttl_seconds=1,
        heartbeat_interval_seconds=1,
        on_promoted=on_p2,
        enabled=True,
    )

    # 1. Start Elector 1 -> promoted
    await elector_1.start()
    assert elector_1.is_leader is True
    assert promoted_1 is True

    # 2. Stop Elector 1 -> gracefully steps down and triggers demoted
    await elector_1.stop()
    assert elector_1.is_leader is False
    assert demoted_1 is True

    # 3. Start Elector 2 -> takes over immediately
    await elector_2.start()
    assert elector_2.is_leader is True
    assert promoted_2 is True

    await elector_2.stop()


def test_disabled_ha_acts_as_standalone_leader():
    """When HA is disabled, instance acts as default leader without DB writes."""
    promoted = False

    def on_p():
        nonlocal promoted
        promoted = True

    elector = LeaderElector(
        get_connection,
        instance_id="inst_standalone",
        on_promoted=on_p,
        enabled=False,
    )

    asyncio.run(elector.start())
    assert elector.is_leader is True
    assert promoted is True

    status = elector.get_status()
    assert status["ha_enabled"] is False
    assert status["is_leader"] is True
