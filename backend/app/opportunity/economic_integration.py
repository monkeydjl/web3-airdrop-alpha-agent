"""Pure, non-networking economic integration over already-persisted collections.

Task 7: gates, run-id helpers, and process_persisted_collection. No collect,
re-persist, HTTP, Settings rollout validation, or emitter construction.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from app.collectors.base import CollectorResult
from app.opportunity.economic_evidence import EconomicEvidenceEmitter
from app.opportunity.economic_writer import EconomicSnapshotWriter, EconomicWriteSummary

if TYPE_CHECKING:
    from app.config import Settings

logger = structlog.get_logger(__name__)

ECONOMIC_SOURCES: frozenset[str] = frozenset({"defillama", "coingecko", "cryptorank"})


def daily_run_id(source_id: str, finished_at: datetime) -> str:
    """Return exact ``daily:<UTC_DATE>:<source_id>`` for the UTC calendar date."""
    utc_dt = finished_at.replace(tzinfo=UTC) if finished_at.tzinfo is None else finished_at.astimezone(UTC)
    return f"daily:{utc_dt.date().isoformat()}:{source_id}"


def manual_run_id(*, uuid_factory: Callable[[], UUID] = uuid.uuid4) -> str:
    """Return exact ``manual:<uuid>``; inject ``uuid_factory`` for tests."""
    return f"manual:{uuid_factory()}"


def economic_source_enabled(source_id: str, settings_obj: Settings) -> bool:
    """True only for the exact triple conjunction of the matching source."""
    if source_id == "defillama":
        return (
            settings_obj.opportunity_economic_snapshot_enabled
            and settings_obj.opportunity_economic_source_defillama_enabled
            and settings_obj.defillama_enabled
        )
    if source_id == "coingecko":
        return (
            settings_obj.opportunity_economic_snapshot_enabled
            and settings_obj.opportunity_economic_source_coingecko_enabled
            and settings_obj.coingecko_enabled
        )
    if source_id == "cryptorank":
        return (
            settings_obj.opportunity_economic_snapshot_enabled
            and settings_obj.opportunity_economic_source_cryptorank_enabled
            and settings_obj.cryptorank_enabled
        )
    return False


def process_persisted_collection(
    result: CollectorResult,
    *,
    run_id: str,
    writer: EconomicSnapshotWriter,
    emitter: EconomicEvidenceEmitter,
    settings_obj: Settings,
) -> EconomicWriteSummary | None:
    """Write snapshots then emit observations for an already-persisted collection.

    Synchronous and non-networking. Never collects, re-persists, or opens HTTP.
    """
    if not economic_source_enabled(result.source_id, settings_obj):
        return None

    try:
        summary: EconomicWriteSummary | None = writer.process(result, run_id=run_id, enabled=True)
    except Exception as exc:
        logger.warning(
            "opportunity.economic.writer_failed",
            source_id=result.source_id,
            run_id=run_id,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        return None

    if summary is None:
        return None

    evidence_enabled = settings_obj.opportunity_economic_evidence_emit_enabled
    for observation in summary.observations:
        try:
            emitter.emit(observation, enabled=evidence_enabled)
        except Exception as exc:
            logger.warning(
                "opportunity.economic.emit_failed",
                source_id=result.source_id,
                run_id=run_id,
                snapshot_id=getattr(observation, "snapshot_id", None),
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            continue

    return summary
