"""Economic time-series resolver and internal proxy projection (Task 6).

Pure read path: verified, in-window Evidence → deep-frozen EconomicProxyProjection
over exactly 12 factor keys. No writes. No generic resolve_factor. No Settings.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Literal

from app.opportunity.economic_models import (
    EconomicProxyProjection,
    EconomicsDataMode,
    ResolvedEconomicFactor,
)
from app.opportunity.economic_repository import EconomicSnapshotRepository
from app.opportunity.models import EvidenceRecord
from app.opportunity.repository import OpportunityRepository

_SNAPSHOT_PREFIX: Final[str] = "econ-snapshot:"

ECONOMIC_FACTOR_KEYS: Final[tuple[str, ...]] = (
    "tvl_usd",
    "tvl_change_7d_ratio",
    "chains_json",
    "token_unlisted_proxy",
    "market_cap_usd",
    "price_usd",
    "volume_24h_usd",
    "circulating_supply",
    "total_supply",
    "market_rank",
    "price_change_24h_ratio",
    "price_change_7d_ratio",
)

_FACTOR_VALUE_TYPE: Final[Mapping[str, Literal["bool", "number", "string", "json"]]] = MappingProxyType(
    {
        "tvl_usd": "string",
        "tvl_change_7d_ratio": "string",
        "chains_json": "json",
        "token_unlisted_proxy": "bool",
        "market_cap_usd": "string",
        "price_usd": "string",
        "volume_24h_usd": "string",
        "circulating_supply": "string",
        "total_supply": "string",
        "market_rank": "number",
        "price_change_24h_ratio": "string",
        "price_change_7d_ratio": "string",
    }
)

_DEFILLAMA_CLASS: Final[frozenset[str]] = frozenset(
    {
        "tvl_usd",
        "tvl_change_7d_ratio",
        "chains_json",
        "token_unlisted_proxy",
    }
)

_MARKET_CLASS: Final[frozenset[str]] = frozenset(
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
)

_RATIO_KEYS: Final[frozenset[str]] = frozenset(
    {
        "tvl_change_7d_ratio",
        "price_change_24h_ratio",
        "price_change_7d_ratio",
    }
)

_MONEY_SUPPLY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "tvl_usd",
        "market_cap_usd",
        "price_usd",
        "volume_24h_usd",
        "circulating_supply",
        "total_supply",
    }
)

_ABS_TOL: Final[Decimal] = Decimal("1e-8")
_PROVIDER_UNMAPPED_RANK: Final[int] = 10_000


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _snapshot_id_from_ref(raw_snapshot_ref: str | None) -> str | None:
    if not isinstance(raw_snapshot_ref, str) or not raw_snapshot_ref:
        return None
    if not raw_snapshot_ref.startswith(_SNAPSHOT_PREFIX):
        return None
    snapshot_id = raw_snapshot_ref[len(_SNAPSHOT_PREFIX) :]
    return snapshot_id if snapshot_id else None


def _provider_rank(factor_key: str, provider: str | None) -> int:
    """Lower is better. Unknown / unmapped last (excluded from preferred ranking)."""
    if provider is None:
        return _PROVIDER_UNMAPPED_RANK
    # Exact lowercase provider mapping only.
    if factor_key in _DEFILLAMA_CLASS:
        if provider == "defillama":
            return 0
        return 100
    if factor_key in _MARKET_CLASS:
        if provider == "coingecko":
            return 0
        if provider == "cryptorank":
            return 1
        return 100
    return 100


def _to_decimal(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        dec = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if not dec.is_finite():
        return None
    return dec


def _values_agree(factor_key: str, left: Any, right: Any) -> bool:
    if factor_key in _MONEY_SUPPLY_KEYS:
        a = _to_decimal(left)
        b = _to_decimal(right)
        if a is None or b is None:
            return left == right
        scale = max(abs(a), abs(b))
        tol = max(_ABS_TOL, _ABS_TOL * scale)
        return abs(a - b) <= tol
    if factor_key in _RATIO_KEYS:
        a = _to_decimal(left)
        b = _to_decimal(right)
        if a is None or b is None:
            return left == right
        return abs(a - b) <= _ABS_TOL
    # JSON / bool / int (and any other exact types): exact equality
    return left == right


def _passes_filter(record: EvidenceRecord, project_id: str, now: datetime) -> bool:
    if record.project_id != project_id:
        return False
    if record.factor_key not in _FACTOR_VALUE_TYPE:
        return False
    if record.verification_status != "verified":
        return False
    if record.effective_at is None:
        return False
    current = _as_utc(now)
    if _as_utc(record.effective_at) > current:
        return False
    if record.expires_at is None:
        return False
    # Equality with now is expired — require strict >
    return _as_utc(record.expires_at) > current


def _absent(factor_key: str) -> ResolvedEconomicFactor:
    return ResolvedEconomicFactor(
        factor_key=factor_key,
        value=None,
        value_type=_FACTOR_VALUE_TYPE[factor_key],
        evidence_id=None,
        conflicted=False,
    )


def _conflicted(factor_key: str) -> ResolvedEconomicFactor:
    return ResolvedEconomicFactor(
        factor_key=factor_key,
        value=None,
        value_type=_FACTOR_VALUE_TYPE[factor_key],
        evidence_id=None,
        conflicted=True,
    )


def _resolved(record: EvidenceRecord) -> ResolvedEconomicFactor:
    value_type = _FACTOR_VALUE_TYPE[record.factor_key]
    # Prefer closed contract type; fall back to record when already matching family.
    record_vt = record.value_type
    if record_vt in {"bool", "number", "string", "json"}:
        value_type = record_vt  # type: ignore[assignment]
    return ResolvedEconomicFactor(
        factor_key=record.factor_key,
        value=record.value,
        value_type=value_type,
        evidence_id=record.evidence_id,
        conflicted=False,
    )


def _mode_from_factors(factors: Mapping[str, ResolvedEconomicFactor]) -> EconomicsDataMode:
    for factor in factors.values():
        if factor.value is not None and factor.conflicted is False:
            return "PROXY_ONLY"
    return "UNKNOWN"


class EconomicResolver:
    def __init__(self, snapshot_repository: EconomicSnapshotRepository) -> None:
        self._snapshot_repository = snapshot_repository

    def resolve(
        self,
        project_id: str,
        records: Sequence[EvidenceRecord],
        *,
        now: datetime,
    ) -> EconomicProxyProjection:
        filtered = [r for r in records if _passes_filter(r, project_id, now)]

        snapshot_ids: list[str] = []
        seen_ids: set[str] = set()
        for record in filtered:
            sid = _snapshot_id_from_ref(record.raw_snapshot_ref)
            if sid is not None and sid not in seen_ids:
                seen_ids.add(sid)
                snapshot_ids.append(sid)

        source_map: dict[str, str] = {}
        if snapshot_ids:
            source_map = self._snapshot_repository.source_ids_by_snapshot_id(snapshot_ids)

        by_factor: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for record in filtered:
            by_factor[record.factor_key].append(record)

        factors: dict[str, ResolvedEconomicFactor] = {}
        for key in ECONOMIC_FACTOR_KEYS:
            factors[key] = self._resolve_one(key, by_factor.get(key, []), source_map)

        mode = _mode_from_factors(factors)
        return EconomicProxyProjection(factors=factors, economics_data_mode=mode)

    def _resolve_one(
        self,
        factor_key: str,
        candidates: list[EvidenceRecord],
        source_map: Mapping[str, str],
    ) -> ResolvedEconomicFactor:
        if not candidates:
            return _absent(factor_key)

        # Group by independence_group; same-group time series → latest only (not conflict).
        by_group: dict[str, list[EvidenceRecord]] = defaultdict(list)
        for record in candidates:
            by_group[record.independence_group].append(record)

        group_winners: list[EvidenceRecord] = []
        for group_records in by_group.values():
            winner = self._pick_group_winner(factor_key, group_records, source_map)
            if winner is not None:
                group_winners.append(winner)

        if not group_winners:
            return _absent(factor_key)

        if len(group_winners) == 1:
            return _resolved(group_winners[0])

        # Inter-group value agreement; disagreement → conflict (no average / bias).
        for i in range(len(group_winners)):
            for j in range(i + 1, len(group_winners)):
                if not _values_agree(factor_key, group_winners[i].value, group_winners[j].value):
                    return _conflicted(factor_key)

        # Values agree: stable winner among group winners.
        final = self._pick_group_winner(factor_key, group_winners, source_map)
        assert final is not None
        return _resolved(final)

    def _pick_group_winner(
        self,
        factor_key: str,
        group_records: list[EvidenceRecord],
        source_map: Mapping[str, str],
    ) -> EvidenceRecord | None:
        if not group_records:
            return None

        def sort_key(record: EvidenceRecord) -> tuple[Any, ...]:
            effective = _as_utc(record.effective_at) if record.effective_at else datetime.min.replace(tzinfo=UTC)
            sid = _snapshot_id_from_ref(record.raw_snapshot_ref)
            provider: str | None = None
            if sid is not None:
                mapped = source_map.get(sid)
                # Exact lowercase provider identity only from mapping.
                if isinstance(mapped, str) and mapped in {
                    "defillama",
                    "coingecko",
                    "cryptorank",
                }:
                    provider = mapped
            # Snapshot ids with no mapping entry are excluded from provider-dependent ranking
            # (worst provider rank). Latest effective_at still primary.
            rank = _provider_rank(factor_key, provider)
            # For same provider: lexical order of snapshot id (ascending).
            snapshot_sort = sid if sid is not None else ""
            evidence_sort = record.evidence_id or ""
            # Sort ascending on (-effective as inverted via reverse); use tuple for min()
            return (
                -effective.timestamp(),
                rank,
                snapshot_sort,
                evidence_sort,
            )

        return min(group_records, key=sort_key)


def project_economics_data(
    project_id: str,
    *,
    evidence_repository: OpportunityRepository,
    snapshot_repository: EconomicSnapshotRepository,
    direct_available: bool,
    now: datetime,
    enabled: bool,
) -> EconomicProxyProjection | None:
    """Load evidence once and project economics data when enabled.

    ``enabled=False`` → ``None`` with zero repository calls.
    """
    if not enabled:
        return None

    records = evidence_repository.list_evidence(project_id)
    projection = EconomicResolver(snapshot_repository).resolve(project_id, records, now=now)
    if direct_available:
        return replace(projection, economics_data_mode="DIRECT_AVAILABLE")
    return projection
