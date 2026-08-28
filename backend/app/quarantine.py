"""Quarantine helpers for dirty raw_projects.

Quarantined rows are excluded from analysis queue until released.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any

import structlog

from app.db import DbConnection, get_connection, scalar

logger = structlog.get_logger(__name__)


def quarantine_raw(
    raw_id: str,
    reason: str,
    *,
    conn: DbConnection | None = None,
) -> bool:
    """Mark a raw_project as quarantined and processed (leave queue)."""
    owns = conn is None
    if conn is None:
        conn = get_connection()
    try:
        # Support raw sqlite3.Connection and DbConnection wrapper
        cur = conn.execute(
            """
            UPDATE raw_projects
            SET quarantined = 1,
                quarantine_reason = ?,
                processed = 1,
                processed_at = CURRENT_TIMESTAMP
            WHERE raw_id = ?
            """,
            (reason[:500], raw_id),
        )
        # If table lacks quarantined cols (old test DBs), fall back to processed only
        if (cur.rowcount or 0) == 0:
            cur = conn.execute(
                """
                UPDATE raw_projects
                SET processed = 1, processed_at = CURRENT_TIMESTAMP
                WHERE raw_id = ?
                """,
                (raw_id,),
            )
        conn.commit()
        ok = (cur.rowcount or 0) > 0
        if ok:
            logger.info("quarantine.set", raw_id=raw_id, reason=reason[:120])
        return ok
    except Exception as e:
        # Column missing on very old schemas → processed-only fallback.
        # 先回滚：Postgres 首条失败后事务进入 aborted 态，不回滚则 fallback 必抛
        # InFailedSqlTransaction 从而掩盖真实异常。
        with suppress(Exception):
            conn.rollback()
        try:
            cur = conn.execute(
                """
                UPDATE raw_projects
                SET processed = 1, processed_at = CURRENT_TIMESTAMP
                WHERE raw_id = ?
                """,
                (raw_id,),
            )
            conn.commit()
            ok = (cur.rowcount or 0) > 0
            if ok:
                logger.info(
                    "quarantine.fallback_processed",
                    raw_id=raw_id,
                    error=str(e)[:120],
                )
            return ok
        except Exception:
            with suppress(Exception):
                conn.rollback()
            raise
    finally:
        if owns:
            conn.close()


def release_quarantine(raw_id: str, *, conn: DbConnection | None = None) -> bool:
    """Clear quarantine and re-queue for analysis."""
    owns = conn is None
    if conn is None:
        conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE raw_projects
            SET quarantined = 0,
                quarantine_reason = NULL,
                processed = 0,
                processed_at = NULL
            WHERE raw_id = ?
            """,
            (raw_id,),
        )
        conn.commit()
        ok = (cur.rowcount or 0) > 0
        if ok:
            logger.info("quarantine.released", raw_id=raw_id)
        return ok
    except Exception:
        with suppress(Exception):
            conn.rollback()
        raise
    finally:
        if owns:
            conn.close()


def list_quarantined(limit: int = 100) -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT raw_id, source_id, dedup_key, raw_data, discovery_score,
                   quarantine_reason, discovered_at
            FROM raw_projects
            WHERE quarantined = 1
            ORDER BY discovered_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def quarantine_count() -> int:
    conn = get_connection()
    try:
        return int(scalar(conn.execute("SELECT COUNT(*) FROM raw_projects WHERE quarantined = 1").fetchone()))
    finally:
        conn.close()
