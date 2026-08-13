"""Non-networking opportunity-economic snapshot writer (Task 4).

Consumes already-persisted ``CollectorResult.items`` only: append-only snapshot
rows via ``EconomicSnapshotRepository``, then builds in-memory
``NormalizedObservation`` via ``observation_from_snapshot``. No HTTP, no
Evidence emit, no identity resolution, no Settings reads.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import structlog

from app.collectors.base import CollectorResult, RawDiscovery
from app.metrics import (
    observe_opportunity_economic_duration,
    record_opportunity_economic_observation,
    record_opportunity_economic_snapshot,
    set_opportunity_economic_last_success,
)
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicSnapshotRow,
    NormalizedObservation,
    build_snapshot_id,
    canonical_json_bytes,
    payload_sha256,
)
from app.opportunity.economic_normalizers import (
    DEFILLAMA_CHANGE_7D_PROVIDER_UNIT,
    PROVIDER_RAW_FIELD_KEYS,
    EconomicNormalizationError,
    canonical_provider_payload,
    normalize_provider_payload,
    sanitize_source_url,
)
from app.opportunity.economic_repository import (
    EconomicSnapshotContentConflict,
    EconomicSnapshotRepository,
)

logger = structlog.get_logger(__name__)

_TTL = timedelta(hours=48)


def utc_now() -> datetime:
    """Return a UTC-aware datetime."""
    return datetime.now(UTC)


@dataclass(frozen=True)
class EconomicWriteSummary:
    source_id: str
    run_id: str
    observations: tuple[NormalizedObservation, ...]
    snapshots_inserted: int
    snapshots_duplicate: int
    schema_invalid: int
    skipped_flag_off: int


class EconomicReconstructionError(ValueError):
    """Snapshot row cannot be reconstructed into a NormalizedObservation."""


def observation_from_snapshot(
    snapshot: EconomicSnapshotRow,
    *,
    normalizer=normalize_provider_payload,
) -> NormalizedObservation:
    """Rebuild a seven-field ``NormalizedObservation`` from a persisted snapshot.

    Validates schema_version, provider-native payload whitelist/hash, DefiLlama
    ``change_7d_unit``, and sanitized ``source_url``. Does not emit Evidence or
    touch identity metrics. Raises on any validation failure.
    """
    if snapshot.schema_version != SCHEMA_VERSION:
        raise EconomicReconstructionError(f"schema_version mismatch: {snapshot.schema_version!r} != {SCHEMA_VERSION!r}")

    # Thaw MappingProxyType / nested freezes to plain JSON-like structures.
    raw_payload = _thaw_mapping(snapshot.payload_json)
    if not isinstance(raw_payload, Mapping):
        raise EconomicReconstructionError("payload_json must be a mapping")

    try:
        rebuilt = canonical_provider_payload(snapshot.source_id, raw_payload)
    except EconomicNormalizationError as exc:
        raise EconomicReconstructionError(str(exc)) from exc

    # Hash of stored payload must equal stored digest; rebuilt must match stored
    # under canonical serialization (whitelist reconstruction equivalence).
    stored_digest = payload_sha256(raw_payload)
    if stored_digest != snapshot.payload_sha256:
        raise EconomicReconstructionError("payload_sha256 mismatch with payload_json")
    if canonical_json_bytes(rebuilt) != canonical_json_bytes(raw_payload):
        raise EconomicReconstructionError("payload_json is not equivalent to provider-native whitelist reconstruction")
    if payload_sha256(rebuilt) != snapshot.payload_sha256:
        raise EconomicReconstructionError("rebuilt payload hash mismatch")

    if snapshot.source_id == "defillama":
        unit = rebuilt.get("change_7d_unit")
        if unit != DEFILLAMA_CHANGE_7D_PROVIDER_UNIT:
            raise EconomicReconstructionError("defillama change_7d_unit must be exact literal 'ratio'")

    try:
        clean_url = sanitize_source_url(snapshot.source_url)
    except EconomicNormalizationError as exc:
        raise EconomicReconstructionError(str(exc)) from exc

    expires_at = snapshot.collected_at
    expires_at = expires_at.replace(tzinfo=UTC) if expires_at.tzinfo is None else expires_at.astimezone(UTC)
    expires_at = expires_at + _TTL

    observed_at = snapshot.collected_at
    observed_at = observed_at.replace(tzinfo=UTC) if observed_at.tzinfo is None else observed_at.astimezone(UTC)

    try:
        factors = normalizer(
            source_id=snapshot.source_id,
            raw_data=rebuilt,
            source_url=clean_url,
            observed_at=observed_at,
            expires_at=expires_at,
        )
    except EconomicNormalizationError as exc:
        raise EconomicReconstructionError(str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive wrap
        raise EconomicReconstructionError(str(exc)) from exc

    return NormalizedObservation(
        snapshot_id=snapshot.snapshot_id,
        source_id=snapshot.source_id,
        dedup_key=snapshot.dedup_key,
        provider_entity_id=snapshot.provider_entity_id,
        factors=factors,
        collected_at=observed_at,
        source_url=clean_url,
    )


def _thaw_mapping(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _thaw_mapping(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_mapping(item) for item in value]
    return value


def _normalize_collected_at(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _strip_query_fragment(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


class EconomicSnapshotWriter:
    """Append economic snapshots and build in-memory observations (no network)."""

    def __init__(
        self,
        repository: EconomicSnapshotRepository,
        *,
        now_factory: Callable[[], datetime] = utc_now,
    ) -> None:
        self._repository = repository
        self._now_factory = now_factory

    def process(
        self,
        result: CollectorResult,
        *,
        run_id: str,
        enabled: bool,
    ) -> EconomicWriteSummary:
        started = time.perf_counter()
        source_id = result.source_id
        observations: list[NormalizedObservation] = []
        snapshots_inserted = 0
        snapshots_duplicate = 0
        schema_invalid = 0
        skipped_flag_off = 0

        try:
            if not enabled:
                for _item in result.items:
                    skipped_flag_off += 1
                    record_opportunity_economic_snapshot(source=source_id, result="skipped_flag_off")
                    record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
                return EconomicWriteSummary(
                    source_id=source_id,
                    run_id=run_id,
                    observations=(),
                    snapshots_inserted=0,
                    snapshots_duplicate=0,
                    schema_invalid=0,
                    skipped_flag_off=skipped_flag_off,
                )

            if result.finished_at is not None:
                collected_at = _normalize_collected_at(result.finished_at)
            else:
                collected_at = _normalize_collected_at(self._now_factory())

            for item in result.items:
                outcome = self._process_item(
                    item,
                    source_id=source_id,
                    run_id=run_id,
                    collected_at=collected_at,
                )
                if outcome == "schema_invalid":
                    schema_invalid += 1
                    continue
                if isinstance(outcome, tuple):
                    snap_result, obs = outcome
                    if snap_result == "inserted":
                        snapshots_inserted += 1
                    elif snap_result == "duplicate":
                        snapshots_duplicate += 1
                    # "error" / content-conflict: neither insert nor schema_invalid
                    if obs is not None:
                        observations.append(obs)

            summary = EconomicWriteSummary(
                source_id=source_id,
                run_id=run_id,
                observations=tuple(observations),
                snapshots_inserted=snapshots_inserted,
                snapshots_duplicate=snapshots_duplicate,
                schema_invalid=schema_invalid,
                skipped_flag_off=skipped_flag_off,
            )
            if observations:
                set_opportunity_economic_last_success(
                    source=source_id,
                    unixtime=time.time(),
                )
            return summary
        finally:
            observe_opportunity_economic_duration(
                source=source_id,
                duration_seconds=time.perf_counter() - started,
            )

    def _process_item(
        self,
        item: RawDiscovery,
        *,
        source_id: str,
        run_id: str,
        collected_at: datetime,
    ) -> str | tuple[str, NormalizedObservation | None]:
        """Process one discovery. Returns summary token or (snap_result, obs|None)."""
        try:
            return self._process_item_inner(
                item,
                source_id=source_id,
                run_id=run_id,
                collected_at=collected_at,
            )
        except Exception as exc:  # unexpected — isolate like repo failure
            logger.warning(
                "opportunity_economic.item_failed",
                source_id=source_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
            return ("error", None)

    def _process_item_inner(
        self,
        item: RawDiscovery,
        *,
        source_id: str,
        run_id: str,
        collected_at: datetime,
    ) -> str | tuple[str, NormalizedObservation | None]:
        # Pre-validate fields used for snapshot construction.
        try:
            dedup_key = item.dedup_key
            if not isinstance(dedup_key, str) or not dedup_key.strip():
                raise EconomicNormalizationError("dedup_key must be non-blank")
            raw_id = item.raw_id
            if not isinstance(raw_id, str) or not raw_id.strip():
                raise EconomicNormalizationError("raw_id must be non-blank")
            if not item.url or not isinstance(item.url, str):
                raise EconomicNormalizationError("url must be a non-blank string")
            # Strip query/fragment before sanitize (sanitize also drops them).
            stripped = _strip_query_fragment(item.url)
            clean_url = sanitize_source_url(stripped)
            if source_id not in PROVIDER_RAW_FIELD_KEYS:
                raise EconomicNormalizationError(f"unknown source_id: {source_id}")
            if not isinstance(item.raw_data, Mapping):
                raise EconomicNormalizationError("raw_data must be a mapping")
            payload = canonical_provider_payload(source_id, item.raw_data)
            # Dry-run normalizer for pre-write schema validation (whole-row).
            expires_at = collected_at + _TTL
            normalize_provider_payload(
                source_id=source_id,
                raw_data=payload,
                source_url=clean_url,
                observed_at=collected_at,
                expires_at=expires_at,
            )
        except (EconomicNormalizationError, ValueError, TypeError) as exc:
            logger.info(
                "opportunity_economic.schema_invalid",
                source_id=source_id,
                error=str(exc),
            )
            record_opportunity_economic_snapshot(source=source_id, result="schema_invalid")
            record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
            return "schema_invalid"

        digest = payload_sha256(payload)
        snapshot_id = build_snapshot_id(
            run_id=run_id,
            source_id=source_id,
            provider_entity_id=raw_id,
            payload_sha256_hex=digest,
        )
        snapshot = EconomicSnapshotRow(
            snapshot_id=snapshot_id,
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            source_id=source_id,
            dedup_key=dedup_key,
            provider_entity_id=raw_id,
            payload_sha256=digest,
            payload_json=payload,
            collected_at=collected_at,
            source_url=clean_url,
        )

        try:
            stored, inserted = self._repository.insert_if_absent(snapshot)
        except EconomicSnapshotContentConflict as exc:
            logger.warning(
                "opportunity_economic.content_conflict",
                source_id=source_id,
                snapshot_id=snapshot_id,
                error=str(exc),
            )
            record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
            return ("error", None)
        except Exception as exc:
            logger.warning(
                "opportunity_economic.repository_error",
                source_id=source_id,
                snapshot_id=snapshot_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
            return ("error", None)

        snap_result = "inserted" if inserted else "duplicate"
        record_opportunity_economic_snapshot(source=source_id, result=snap_result)

        try:
            observation = observation_from_snapshot(stored)
        except Exception as exc:
            logger.warning(
                "opportunity_economic.reconstruction_failed",
                source_id=source_id,
                snapshot_id=stored.snapshot_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            # Snapshot retained; observation not built. Not schema_invalid
            # (snapshot already persisted successfully).
            record_opportunity_economic_observation(source=source_id, result="skipped_no_snapshot")
            return (snap_result, None)

        record_opportunity_economic_observation(source=source_id, result="built")
        return (snap_result, observation)
