"""Economic Evidence emit + post-link replay (Task 5).

Fully local, append-only insert-if-absent. Explicit ``enabled`` only — never
reads Settings. Reuses ``observation_from_snapshot`` for reconstruction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Final

import structlog
from pydantic import HttpUrl

from app.metrics import (
    record_opportunity_economic_evidence,
    record_opportunity_economic_identity,
)
from app.opportunity.economic_models import (
    NormalizedFactor,
    NormalizedObservation,
    build_evidence_id,
)
from app.opportunity.economic_repository import EconomicSnapshotRepository
from app.opportunity.economic_writer import observation_from_snapshot
from app.opportunity.models import EvidenceRecord
from app.opportunity.repository import (
    EconomicEvidenceContentConflict,
    OpportunityRepository,
)

logger = structlog.get_logger(__name__)

_TTL = timedelta(hours=48)

# Closed factor keys per provider (whitelist only; values already canonical).
_PROVIDER_FACTOR_WHITELIST: Final[dict[str, frozenset[str]]] = {
    "defillama": frozenset(
        {
            "tvl_usd",
            "tvl_change_7d_ratio",
            "chains_json",
            "token_unlisted_proxy",
        }
    ),
    "coingecko": frozenset(
        {
            "market_cap_usd",
            "price_usd",
            "volume_24h_usd",
            "circulating_supply",
            "market_rank",
            "price_change_24h_ratio",
        }
    ),
    "cryptorank": frozenset(
        {
            "market_cap_usd",
            "price_usd",
            "volume_24h_usd",
            "circulating_supply",
            "total_supply",
            "market_rank",
            "price_change_24h_ratio",
            "price_change_7d_ratio",
        }
    ),
}

_VALUE_TYPE_BY_FACTOR: Final[dict[str, str]] = {
    "tvl_usd": "string",
    "tvl_change_7d_ratio": "string",
    "market_cap_usd": "string",
    "price_usd": "string",
    "volume_24h_usd": "string",
    "circulating_supply": "string",
    "total_supply": "string",
    "price_change_24h_ratio": "string",
    "price_change_7d_ratio": "string",
    "chains_json": "json",
    "token_unlisted_proxy": "bool",
    "market_rank": "number",
}

_SOURCE_META: Final[dict[str, tuple[str, str]]] = {
    "defillama": ("public_aggregator", "defillama-protocols"),
    "coingecko": ("public_market_data", "market-aggregators"),
    "cryptorank": ("public_market_data", "market-aggregators"),
}


@dataclass(frozen=True)
class EconomicEvidenceSummary:
    emitted: int
    duplicates: int
    unlinked: int
    conflicts: int
    skipped_flag_off: int


class EconomicEvidenceEmitter:
    def __init__(
        self,
        conn: Any,
        snapshot_repository: EconomicSnapshotRepository,
        evidence_repository: OpportunityRepository,
    ) -> None:
        self._conn = conn
        self._snapshot_repository = snapshot_repository
        self._evidence_repository = evidence_repository

    def emit(
        self,
        observation: NormalizedObservation,
        *,
        enabled: bool,
    ) -> EconomicEvidenceSummary:
        source = observation.source_id
        if not enabled:
            record_opportunity_economic_evidence(source=source, result="skipped_flag_off")
            return EconomicEvidenceSummary(
                emitted=0,
                duplicates=0,
                unlinked=0,
                conflicts=0,
                skipped_flag_off=1,
            )

        project_id = self._snapshot_repository.find_linked_project_id(
            observation.source_id,
            observation.dedup_key,
        )
        if project_id is None:
            record_opportunity_economic_identity(source=source, result="unlinked")
            record_opportunity_economic_evidence(source=source, result="skipped_no_project")
            return EconomicEvidenceSummary(
                emitted=0,
                duplicates=0,
                unlinked=1,
                conflicts=0,
                skipped_flag_off=0,
            )

        record_opportunity_economic_identity(source=source, result="linked")

        allowed = _PROVIDER_FACTOR_WHITELIST.get(source, frozenset())
        source_type, independence_group = _SOURCE_META.get(source, ("public_market_data", "market-aggregators"))
        collected = observation.collected_at
        expires_at = collected + _TTL

        emitted = 0
        duplicates = 0
        conflicts = 0

        for factor in observation.factors:
            if factor.factor_key not in allowed:
                continue
            expected_vt = _VALUE_TYPE_BY_FACTOR.get(factor.factor_key)
            if expected_vt is None or factor.value_type != expected_vt:
                # Closed value_type contract — skip mismatched factor keys/types.
                continue
            evidence = _build_evidence_record(
                observation=observation,
                factor=factor,
                project_id=project_id,
                source_type=source_type,
                independence_group=independence_group,
                effective_at=collected,
                expires_at=expires_at,
            )
            try:
                _stored, inserted = self._evidence_repository.add_economic_evidence_if_absent(evidence)
            except EconomicEvidenceContentConflict:
                conflicts += 1
                record_opportunity_economic_evidence(source=source, result="content_conflict")
                continue
            if inserted:
                emitted += 1
                record_opportunity_economic_evidence(source=source, result="emitted")
            else:
                duplicates += 1
                record_opportunity_economic_evidence(source=source, result="duplicate")

        return EconomicEvidenceSummary(
            emitted=emitted,
            duplicates=duplicates,
            unlinked=0,
            conflicts=conflicts,
            skipped_flag_off=0,
        )


def _build_evidence_record(
    *,
    observation: NormalizedObservation,
    factor: NormalizedFactor,
    project_id: str,
    source_type: str,
    independence_group: str,
    effective_at: Any,
    expires_at: Any,
) -> EvidenceRecord:
    evidence_id = build_evidence_id(
        snapshot_id=observation.snapshot_id,
        project_id=project_id,
        factor_key=factor.factor_key,
    )
    return EvidenceRecord(
        evidence_id=evidence_id,
        project_id=project_id,
        factor_key=factor.factor_key,
        value=factor.value,
        value_type=factor.value_type,
        observation_type="observed",
        source_url=HttpUrl(factor.source_url or observation.source_url),
        source_type=source_type,
        source_grade="C",
        observed_at=factor.observed_at,
        effective_at=effective_at,
        expires_at=expires_at,
        verification_status="verified",
        independence_group=independence_group,
        raw_snapshot_ref=f"econ-snapshot:{observation.snapshot_id}",
        supersedes_evidence_id=None,
    )


def replay_economic_snapshots_for_project(
    project_id: str,
    *,
    conn: Any,
    enabled: bool,
) -> EconomicEvidenceSummary | None:
    """Replay linked economic snapshots into Evidence for one project.

    ``enabled=False`` returns exactly ``None`` immediately with zero snapshot
    query, reconstruction, Evidence I/O, and identity/evidence metric samples.
    """
    if not enabled:
        return None

    snapshot_repository = EconomicSnapshotRepository(conn)
    evidence_repository = OpportunityRepository(conn)
    emitter = EconomicEvidenceEmitter(conn, snapshot_repository, evidence_repository)

    identities = conn.execute(
        """
        SELECT DISTINCT source_id, dedup_key
        FROM raw_projects
        WHERE project_id = ?
          AND project_id IS NOT NULL
          AND TRIM(project_id) != ''
        """,
        (project_id,),
    ).fetchall()

    total = EconomicEvidenceSummary(
        emitted=0,
        duplicates=0,
        unlinked=0,
        conflicts=0,
        skipped_flag_off=0,
    )

    for row in identities:
        source_id = row["source_id"]
        dedup_key = row["dedup_key"]
        snapshots = snapshot_repository.list_by_identity(source_id, dedup_key)
        for snapshot in snapshots:
            try:
                observation = observation_from_snapshot(snapshot)
            except Exception as exc:
                logger.warning(
                    "opportunity_economic.replay_reconstruction_failed",
                    project_id=project_id,
                    snapshot_id=snapshot.snapshot_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                continue
            part = emitter.emit(observation, enabled=True)
            total = EconomicEvidenceSummary(
                emitted=total.emitted + part.emitted,
                duplicates=total.duplicates + part.duplicates,
                unlinked=total.unlinked + part.unlinked,
                conflicts=total.conflicts + part.conflicts,
                skipped_flag_off=total.skipped_flag_off + part.skipped_flag_off,
            )

    return total
