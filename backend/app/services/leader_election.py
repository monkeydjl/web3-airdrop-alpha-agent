"""Multi-Instance High Availability & Leader Election (W12-03, ADR-005).

Provides distributed leader election and heartbeat leases to ensure that only
a single instance in a multi-replica deployment activates scheduled jobs
(UnifiedScheduler), preventing duplicate execution, resource contention, and split-brain.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any
import uuid

import structlog

from app.config import settings
from app.db import DbConnection, dict_from_row, get_connection

logger = structlog.get_logger(__name__)

CallbackType = Callable[[], Awaitable[None] | None]


class LeaderElector:
    """Leader Election and Heartbeat Lease Manager."""

    def __init__(
        self,
        conn_factory: Callable[[], DbConnection] | None = None,
        *,
        resource_id: str = "unified_scheduler",
        instance_id: str | None = None,
        lease_ttl_seconds: int | None = None,
        heartbeat_interval_seconds: int | None = None,
        on_promoted: CallbackType | None = None,
        on_demoted: CallbackType | None = None,
        enabled: bool | None = None,
    ) -> None:
        self.conn_factory = conn_factory or get_connection
        self.resource_id = resource_id
        self.instance_id = (
            instance_id
            or (settings.ha_instance_id.strip() if settings.ha_instance_id else None)
            or f"inst_{uuid.uuid4().hex[:12]}"
        )
        self.lease_ttl_seconds = lease_ttl_seconds or settings.ha_lease_ttl_seconds
        self.heartbeat_interval_seconds = heartbeat_interval_seconds or settings.ha_heartbeat_interval_seconds
        self.on_promoted = on_promoted
        self.on_demoted = on_demoted
        self.enabled = settings.ha_enabled if enabled is None else enabled

        self._is_leader = False
        self._running = False
        self._task: asyncio.Task[None] | None = None
        self._logger = logger.bind(component="leader_election", instance_id=self.instance_id)

    @property
    def is_leader(self) -> bool:
        """Whether this instance currently holds leadership."""
        return self._is_leader

    def acquire_or_renew(self) -> bool:
        """Attempt to acquire leadership or renew current lease.

        Uses serialized write transaction with optimistic concurrency check.
        Returns True if this instance is now the leader, False otherwise.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=self.lease_ttl_seconds)

        with self.conn_factory() as conn:
            conn.begin_serialized_write()
            try:
                row = conn.execute(
                    "SELECT leader_id, lease_expires_at, version FROM leader_election WHERE resource_id = ?",
                    (self.resource_id,),
                ).fetchone()

                if row is None:
                    # 1. No existing lease -> insert initial lease
                    conn.execute(
                        """
                        INSERT INTO leader_election (resource_id, leader_id, lease_expires_at, acquired_at, version)
                        VALUES (?, ?, ?, ?, 1)
                        """,
                        (self.resource_id, self.instance_id, expires_at, now),
                    )
                    conn.commit()
                    self._is_leader = True
                    self._logger.info(
                        "ha.lease_renewed",
                        resource_id=self.resource_id,
                        instance_id=self.instance_id,
                        action="initial_acquire",
                    )
                    return True

                data = dict_from_row(row)
                current_leader = data["leader_id"]
                current_expires = data["lease_expires_at"]
                version = data["version"]

                # Parse expiration timestamp to UTC datetime if string
                if isinstance(current_expires, str):
                    try:
                        current_expires = datetime.fromisoformat(current_expires.replace(" ", "T"))
                    except Exception:
                        current_expires = now - timedelta(seconds=1)
                if current_expires.tzinfo is None:
                    current_expires = current_expires.replace(tzinfo=UTC)

                if current_leader == self.instance_id:
                    # 2. Already leader -> renew lease
                    cur = conn.execute(
                        """
                        UPDATE leader_election
                        SET lease_expires_at = ?, version = version + 1
                        WHERE resource_id = ? AND version = ?
                        """,
                        (expires_at, self.resource_id, version),
                    )
                    conn.commit()
                    if cur.rowcount and cur.rowcount > 0:
                        self._is_leader = True
                        self._logger.debug(
                            "ha.lease_renewed",
                            resource_id=self.resource_id,
                            instance_id=self.instance_id,
                            action="renew",
                        )
                        return True
                    self._is_leader = False
                    return False

                if current_expires < now:
                    # 3. Existing lease expired -> takeover / failover
                    cur = conn.execute(
                        """
                        UPDATE leader_election
                        SET leader_id = ?, lease_expires_at = ?, acquired_at = ?, version = version + 1
                        WHERE resource_id = ? AND version = ?
                        """,
                        (self.instance_id, expires_at, now, self.resource_id, version),
                    )
                    conn.commit()
                    if cur.rowcount and cur.rowcount > 0:
                        self._is_leader = True
                        self._logger.info(
                            "ha.lease_renewed",
                            resource_id=self.resource_id,
                            instance_id=self.instance_id,
                            previous_leader=current_leader,
                            action="takeover",
                        )
                        return True
                    self._is_leader = False
                    return False

                # 4. Another leader holds active lease
                self._is_leader = False
                return False
            except Exception as exc:
                conn.rollback()
                self._is_leader = False
                self._logger.error(
                    "ha.election_failed",
                    resource_id=self.resource_id,
                    error=str(exc),
                )
                return False

    def step_down(self) -> bool:
        """Voluntarily release leadership lease on graceful shutdown."""
        if not self._is_leader:
            return False

        now = datetime.now(UTC)
        with self.conn_factory() as conn:
            conn.begin_serialized_write()
            try:
                conn.execute(
                    """
                    UPDATE leader_election
                    SET lease_expires_at = ?
                    WHERE resource_id = ? AND leader_id = ?
                    """,
                    (now, self.resource_id, self.instance_id),
                )
                conn.commit()
                self._is_leader = False
                self._logger.info(
                    "ha.leader_stepped_down",
                    resource_id=self.resource_id,
                    instance_id=self.instance_id,
                )
                return True
            except Exception as exc:
                conn.rollback()
                self._logger.error(
                    "ha.election_failed",
                    resource_id=self.resource_id,
                    action="step_down",
                    error=str(exc),
                )
                return False

    def get_status(self) -> dict[str, Any]:
        """Query current cluster leadership and lease status."""
        now = datetime.now(UTC)
        current_leader = None
        lease_expires_at = None
        acquired_at = None
        version = 0

        try:
            with self.conn_factory() as conn:
                row = conn.execute(
                    "SELECT leader_id, lease_expires_at, acquired_at, version FROM leader_election WHERE resource_id = ?",
                    (self.resource_id,),
                ).fetchone()
                if row:
                    data = dict_from_row(row)
                    current_leader = data.get("leader_id")
                    lease_expires_at = str(data.get("lease_expires_at"))
                    acquired_at = str(data.get("acquired_at"))
                    version = data.get("version", 0)
        except Exception:
            pass

        if not self.enabled:
            status_str = "standalone"
        elif self._is_leader:
            status_str = "leader"
        else:
            status_str = "follower"

        return {
            "ha_enabled": self.enabled,
            "resource_id": self.resource_id,
            "instance_id": self.instance_id,
            "is_leader": self._is_leader,
            "current_leader": current_leader,
            "lease_expires_at": lease_expires_at,
            "acquired_at": acquired_at,
            "version": version,
            "lease_ttl_seconds": self.lease_ttl_seconds,
            "heartbeat_interval_seconds": self.heartbeat_interval_seconds,
            "status": status_str,
        }

    async def start(self) -> None:
        """Start background election and heartbeat loop."""
        if not self.enabled:
            # When HA is disabled, instance acts as default leader without election
            self._is_leader = True
            if self.on_promoted:
                res = self.on_promoted()
                if asyncio.iscoroutine(res):
                    await res
            return

        self._running = True
        # Perform initial election synchronously
        await self._tick()
        self._task = asyncio.create_task(self._election_loop())

    async def stop(self) -> None:
        """Stop background loop and gracefully step down if leader."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        if self._is_leader:
            self.step_down()
            if self.on_demoted:
                res = self.on_demoted()
                if asyncio.iscoroutine(res):
                    await res

    async def _tick(self) -> None:
        """Single heartbeat/election iteration."""
        was_leader = self._is_leader
        try:
            won = self.acquire_or_renew()
            if won and not was_leader:
                self._is_leader = True
                self._logger.info(
                    "ha.leader_promoted",
                    resource_id=self.resource_id,
                    instance_id=self.instance_id,
                )
                if self.on_promoted:
                    res = self.on_promoted()
                    if asyncio.iscoroutine(res):
                        await res
            elif not won and was_leader:
                self._is_leader = False
                self._logger.warning(
                    "ha.leader_demoted",
                    resource_id=self.resource_id,
                    instance_id=self.instance_id,
                )
                if self.on_demoted:
                    res = self.on_demoted()
                    if asyncio.iscoroutine(res):
                        await res
        except Exception as exc:
            self._logger.error(
                "ha.election_failed",
                resource_id=self.resource_id,
                instance_id=self.instance_id,
                error=str(exc),
            )

    async def _election_loop(self) -> None:
        """Continuous heartbeat and election polling loop."""
        while self._running:
            await asyncio.sleep(self.heartbeat_interval_seconds)
            if not self._running:
                break
            await self._tick()
