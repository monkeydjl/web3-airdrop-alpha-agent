"""Task 6: EconomicResolver time-series projection and project_economics_data."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.db import DbConnection, init_db
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicSnapshotRow,
    build_snapshot_id,
    payload_sha256,
)
from app.opportunity.models import EvidenceRecord

# Exact 12 keys in frozen order from Task 6 brief.
_TWELVE_KEYS = (
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

_NOW = datetime(2026, 7, 23, 12, 0, tzinfo=UTC)
_COLLECTED = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
_EXPIRES = _COLLECTED + timedelta(hours=48)


def _make_snapshot(
    *,
    source_id: str = "defillama",
    dedup_key: str = "protocol:example",
    provider_entity_id: str = "raw-example-1",
    run_id: str = "daily:2026-07-22:defillama",
    payload: dict[str, Any] | None = None,
) -> EconomicSnapshotRow:
    body = payload if payload is not None else {"tvl": 1_000_000, "change_7d": 0.05, "change_7d_unit": "ratio"}
    digest = payload_sha256(body)
    snapshot_id = build_snapshot_id(
        run_id=run_id,
        source_id=source_id,
        provider_entity_id=provider_entity_id,
        payload_sha256_hex=digest,
    )
    return EconomicSnapshotRow(
        snapshot_id=snapshot_id,
        schema_version=SCHEMA_VERSION,
        run_id=run_id,
        source_id=source_id,
        dedup_key=dedup_key,
        provider_entity_id=provider_entity_id,
        payload_sha256=digest,
        payload_json=body,
        source_url=f"https://example.com/{source_id}",
        collected_at=_COLLECTED,
    )


def _sqlite_snapshot_repo():
    from app.opportunity.economic_repository import EconomicSnapshotRepository

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return raw, conn, EconomicSnapshotRepository(conn)


def _evidence(
    *,
    evidence_id: str = "ev-1",
    project_id: str = "proj-1",
    factor_key: str = "tvl_usd",
    value: Any = "1000000.00000000",
    value_type: str = "string",
    verification_status: str = "verified",
    effective_at: datetime | None = _COLLECTED,
    expires_at: datetime | None = _EXPIRES,
    independence_group: str = "defillama-protocols",
    raw_snapshot_ref: str | None = None,
    source_type: str = "public_aggregator",
    observed_at: datetime | None = None,
) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=evidence_id,
        project_id=project_id,
        factor_key=factor_key,
        value=value,
        value_type=value_type,  # type: ignore[arg-type]
        observation_type="observed",
        source_url="https://example.com/econ",
        source_type=source_type,
        source_grade="C",
        observed_at=observed_at or effective_at or _COLLECTED,
        effective_at=effective_at,
        expires_at=expires_at,
        verification_status=verification_status,  # type: ignore[arg-type]
        independence_group=independence_group,
        raw_snapshot_ref=raw_snapshot_ref,
        supersedes_evidence_id=None,
    )


def test_resolve_always_returns_exactly_twelve_deep_frozen_keys() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        resolver = EconomicResolver(snap_repo)
        projection = resolver.resolve("proj-1", [], now=_NOW)

        assert list(projection.factors.keys()) == list(_TWELVE_KEYS)
        assert isinstance(projection.factors, MappingProxyType)
        for key in _TWELVE_KEYS:
            factor = projection.factors[key]
            assert factor.factor_key == key
            assert factor.value is None
            assert factor.evidence_id is None
            assert factor.conflicted is False
            assert not hasattr(factor, "raw_snapshot_ref")
            with pytest.raises((TypeError, AttributeError)):
                factor.conflicted = True  # type: ignore[misc]
        with pytest.raises(TypeError):
            projection.factors["tvl_usd"] = projection.factors["tvl_usd"]  # type: ignore[index]
        assert projection.economics_data_mode == "UNKNOWN"
    finally:
        snap_repo.close()
        conn.close()


def test_filter_excludes_wrong_project_unverified_out_of_window_expired_equality() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap = _make_snapshot()
        snap_repo.insert_if_absent(snap)
        ref = f"econ-snapshot:{snap.snapshot_id}"

        records = [
            _evidence(
                evidence_id="wrong-project",
                project_id="other",
                raw_snapshot_ref=ref,
                value="1.00000000",
            ),
            _evidence(
                evidence_id="unverified",
                verification_status="unverified",
                raw_snapshot_ref=ref,
                value="2.00000000",
            ),
            _evidence(
                evidence_id="future-effective",
                effective_at=_NOW + timedelta(hours=1),
                expires_at=_NOW + timedelta(hours=49),
                raw_snapshot_ref=ref,
                value="3.00000000",
            ),
            _evidence(
                evidence_id="expired-equality",
                effective_at=_COLLECTED,
                expires_at=_NOW,  # equality with now is expired
                raw_snapshot_ref=ref,
                value="4.00000000",
            ),
            _evidence(
                evidence_id="null-expires",
                expires_at=None,
                raw_snapshot_ref=ref,
                value="5.00000000",
            ),
            _evidence(
                evidence_id="wrong-key",
                factor_key="not_a_closed_key",
                raw_snapshot_ref=ref,
                value="6.00000000",
            ),
        ]
        resolver = EconomicResolver(snap_repo)
        projection = resolver.resolve("proj-1", records, now=_NOW)
        assert projection.factors["tvl_usd"].value is None
        assert projection.factors["tvl_usd"].conflicted is False
        assert projection.economics_data_mode == "UNKNOWN"
    finally:
        snap_repo.close()
        conn.close()


def test_resolved_single_factor_proxy_only_and_no_raw_snapshot_ref() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap = _make_snapshot()
        snap_repo.insert_if_absent(snap)
        records = [
            _evidence(
                evidence_id="tvl-win",
                value="1500000.00000000",
                raw_snapshot_ref=f"econ-snapshot:{snap.snapshot_id}",
            )
        ]
        resolver = EconomicResolver(snap_repo)
        projection = resolver.resolve("proj-1", records, now=_NOW)
        factor = projection.factors["tvl_usd"]
        assert factor.value == "1500000.00000000"
        assert factor.evidence_id == "tvl-win"
        assert factor.conflicted is False
        assert factor.value_type == "string"
        assert not hasattr(factor, "raw_snapshot_ref")
        assert "raw_snapshot_ref" not in factor.__dataclass_fields__
        assert projection.economics_data_mode == "PROXY_ONLY"
    finally:
        snap_repo.close()
        conn.close()


def test_batch_source_lookup_once_for_nonempty_refs_zero_for_empty() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_a = _make_snapshot(provider_entity_id="ent-a")
        snap_b = _make_snapshot(
            provider_entity_id="ent-b",
            run_id="daily:2026-07-22:defillama-b",
        )
        snap_repo.insert_if_absent(snap_a)
        snap_repo.insert_if_absent(snap_b)

        calls: list[list[str]] = []
        original = snap_repo.source_ids_by_snapshot_id

        def _spy(snapshot_ids):
            materialised = list(snapshot_ids)
            calls.append(materialised)
            return original(materialised)

        snap_repo.source_ids_by_snapshot_id = _spy  # type: ignore[method-assign]

        # Empty usable refs → no batch call needed (no econ-snapshot refs)
        resolver = EconomicResolver(snap_repo)
        resolver.resolve(
            "proj-1",
            [_evidence(evidence_id="no-ref", raw_snapshot_ref=None, value="1.00000000")],
            now=_NOW,
        )
        # Records without econ-snapshot: prefix may still resolve if no provider needed for single candidate;
        # batch only when nonempty snapshot ids collected.
        # With raw_snapshot_ref=None, snapshot id list is empty → zero batch calls.
        assert calls == []

        calls.clear()
        records = [
            _evidence(
                evidence_id="a",
                value="10.00000000",
                raw_snapshot_ref=f"econ-snapshot:{snap_a.snapshot_id}",
            ),
            _evidence(
                evidence_id="b",
                value="20.00000000",
                effective_at=_COLLECTED + timedelta(hours=1),
                raw_snapshot_ref=f"econ-snapshot:{snap_b.snapshot_id}",
            ),
            _evidence(
                evidence_id="bad-prefix",
                value="30.00000000",
                raw_snapshot_ref="other:not-econ",
            ),
        ]
        projection = resolver.resolve("proj-1", records, now=_NOW)
        assert len(calls) == 1
        assert set(calls[0]) == {snap_a.snapshot_id, snap_b.snapshot_id}
        # Latest effective_at wins within group
        assert projection.factors["tvl_usd"].evidence_id == "b"
        assert projection.factors["tvl_usd"].value == "20.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_same_group_time_series_not_conflict_latest_wins() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        yesterday = _make_snapshot(run_id="daily:2026-07-21:defillama", provider_entity_id="y")
        today = _make_snapshot(run_id="daily:2026-07-22:defillama", provider_entity_id="t")
        snap_repo.insert_if_absent(yesterday)
        snap_repo.insert_if_absent(today)
        records = [
            _evidence(
                evidence_id="yest",
                value="100.00000000",
                effective_at=_COLLECTED - timedelta(days=1),
                expires_at=_EXPIRES,
                raw_snapshot_ref=f"econ-snapshot:{yesterday.snapshot_id}",
            ),
            _evidence(
                evidence_id="tod",
                value="200.00000000",
                effective_at=_COLLECTED,
                expires_at=_EXPIRES,
                raw_snapshot_ref=f"econ-snapshot:{today.snapshot_id}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        factor = projection.factors["tvl_usd"]
        assert factor.conflicted is False
        assert factor.value == "200.00000000"
        assert factor.evidence_id == "tod"
    finally:
        snap_repo.close()
        conn.close()


def test_market_provider_tie_prefers_coingecko_over_cryptorank() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_cr = _make_snapshot(
            source_id="cryptorank",
            dedup_key="coin:x",
            provider_entity_id="cr",
            run_id="daily:2026-07-22:cryptorank",
            payload={"market_cap": 1, "price": 2},
        )
        snap_cg = _make_snapshot(
            source_id="coingecko",
            dedup_key="coin:x",
            provider_entity_id="cg",
            run_id="daily:2026-07-22:coingecko",
            payload={"market_cap": 1, "current_price": 2},
        )
        snap_repo.insert_if_absent(snap_cr)
        snap_repo.insert_if_absent(snap_cg)
        # Same effective_at → provider priority: coingecko > cryptorank
        records = [
            _evidence(
                evidence_id="cr-mc",
                factor_key="market_cap_usd",
                value="100.00000000",
                independence_group="market-aggregators",
                source_type="public_market_data",
                raw_snapshot_ref=f"econ-snapshot:{snap_cr.snapshot_id}",
            ),
            _evidence(
                evidence_id="cg-mc",
                factor_key="market_cap_usd",
                value="999.00000000",
                independence_group="market-aggregators",
                source_type="public_market_data",
                raw_snapshot_ref=f"econ-snapshot:{snap_cg.snapshot_id}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        factor = projection.factors["market_cap_usd"]
        assert factor.conflicted is False
        assert factor.evidence_id == "cg-mc"
        assert factor.value == "999.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_same_provider_tie_uses_lexical_snapshot_id() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        # Force two distinct snapshot ids under same provider with same effective_at
        snap_z = _make_snapshot(provider_entity_id="z-entity", run_id="daily:2026-07-22:z")
        snap_a = _make_snapshot(provider_entity_id="a-entity", run_id="daily:2026-07-22:a")
        snap_repo.insert_if_absent(snap_z)
        snap_repo.insert_if_absent(snap_a)
        # Ensure we know which is lexicographically smaller
        ids = sorted([snap_z.snapshot_id, snap_a.snapshot_id])
        smaller, larger = ids[0], ids[1]
        records = [
            _evidence(
                evidence_id="ev-larger",
                value="1.00000000",
                raw_snapshot_ref=f"econ-snapshot:{larger}",
            ),
            _evidence(
                evidence_id="ev-smaller",
                value="2.00000000",
                raw_snapshot_ref=f"econ-snapshot:{smaller}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        assert projection.factors["tvl_usd"].evidence_id == "ev-smaller"
        assert projection.factors["tvl_usd"].value == "2.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_inter_group_money_disagreement_is_conflict_no_average() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        # Two independent groups with disagreeing money values → conflict
        snap_dl = _make_snapshot(source_id="defillama", provider_entity_id="dl")
        snap_other = _make_snapshot(
            source_id="coingecko",
            provider_entity_id="cg",
            run_id="daily:2026-07-22:coingecko",
            payload={"market_cap": 1},
        )
        snap_repo.insert_if_absent(snap_dl)
        snap_repo.insert_if_absent(snap_other)
        records = [
            _evidence(
                evidence_id="g1",
                factor_key="tvl_usd",
                value="100.00000000",
                independence_group="group-a",
                raw_snapshot_ref=f"econ-snapshot:{snap_dl.snapshot_id}",
            ),
            _evidence(
                evidence_id="g2",
                factor_key="tvl_usd",
                value="200.00000000",
                independence_group="group-b",
                raw_snapshot_ref=f"econ-snapshot:{snap_other.snapshot_id}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        factor = projection.factors["tvl_usd"]
        assert factor.value is None
        assert factor.evidence_id is None
        assert factor.conflicted is True
        # No averaging
        assert factor.value != "150.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_inter_group_money_agreement_within_tolerance_resolves() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_a = _make_snapshot(provider_entity_id="a")
        snap_b = _make_snapshot(provider_entity_id="b", run_id="daily:2026-07-22:b")
        snap_repo.insert_if_absent(snap_a)
        snap_repo.insert_if_absent(snap_b)
        # abs(a-b) <= max(1e-8, 1e-8 * max(|a|,|b|)) for large values is relative
        a = "1000000.00000000"
        b = "1000000.00001000"  # diff 1e-5 absolute on 1e6 → relative 1e-11 < 1e-8?
        # abs diff = 0.00001 = 1e-5; max(1e-8, 1e-8 * 1e6) = max(1e-8, 1e-2) = 1e-2
        # 1e-5 <= 1e-2 → agree
        records = [
            _evidence(
                evidence_id="agree-a",
                value=a,
                independence_group="g-a",
                raw_snapshot_ref=f"econ-snapshot:{snap_a.snapshot_id}",
            ),
            _evidence(
                evidence_id="agree-b",
                value=b,
                independence_group="g-b",
                raw_snapshot_ref=f"econ-snapshot:{snap_b.snapshot_id}",
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        factor = projection.factors["tvl_usd"]
        assert factor.conflicted is False
        assert factor.value is not None
        assert factor.evidence_id in {"agree-a", "agree-b"}
    finally:
        snap_repo.close()
        conn.close()


def test_ratio_absolute_tolerance_and_exact_bool_json_int() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_a = _make_snapshot(provider_entity_id="ra")
        snap_b = _make_snapshot(provider_entity_id="rb", run_id="daily:2026-07-22:rb")
        snap_repo.insert_if_absent(snap_a)
        snap_repo.insert_if_absent(snap_b)
        ref_a = f"econ-snapshot:{snap_a.snapshot_id}"
        ref_b = f"econ-snapshot:{snap_b.snapshot_id}"

        # Ratio: abs <= 1e-8 agrees
        ratio_records = [
            _evidence(
                evidence_id="r1",
                factor_key="tvl_change_7d_ratio",
                value="0.05000000",
                independence_group="g1",
                raw_snapshot_ref=ref_a,
            ),
            _evidence(
                evidence_id="r2",
                factor_key="tvl_change_7d_ratio",
                value="0.05000000",
                independence_group="g2",
                raw_snapshot_ref=ref_b,
            ),
        ]
        # Bool exact
        bool_records = [
            _evidence(
                evidence_id="b1",
                factor_key="token_unlisted_proxy",
                value=True,
                value_type="bool",
                independence_group="g1",
                raw_snapshot_ref=ref_a,
            ),
            _evidence(
                evidence_id="b2",
                factor_key="token_unlisted_proxy",
                value=False,
                value_type="bool",
                independence_group="g2",
                raw_snapshot_ref=ref_b,
            ),
        ]
        # JSON exact
        json_records = [
            _evidence(
                evidence_id="j1",
                factor_key="chains_json",
                value=["ethereum", "base"],
                value_type="json",
                independence_group="g1",
                raw_snapshot_ref=ref_a,
            ),
            _evidence(
                evidence_id="j2",
                factor_key="chains_json",
                value=["ethereum", "base"],
                value_type="json",
                independence_group="g2",
                raw_snapshot_ref=ref_b,
            ),
        ]
        # market_rank int exact disagree
        rank_records = [
            _evidence(
                evidence_id="m1",
                factor_key="market_rank",
                value=10,
                value_type="number",
                independence_group="g1",
                raw_snapshot_ref=ref_a,
            ),
            _evidence(
                evidence_id="m2",
                factor_key="market_rank",
                value=11,
                value_type="number",
                independence_group="g2",
                raw_snapshot_ref=ref_b,
            ),
        ]
        projection = EconomicResolver(snap_repo).resolve(
            "proj-1",
            ratio_records + bool_records + json_records + rank_records,
            now=_NOW,
        )
        assert projection.factors["tvl_change_7d_ratio"].conflicted is False
        assert projection.factors["tvl_change_7d_ratio"].value == "0.05000000"
        assert projection.factors["token_unlisted_proxy"].conflicted is True
        assert projection.factors["token_unlisted_proxy"].value is None
        assert projection.factors["chains_json"].conflicted is False
        # Deep-frozen nested JSON
        chains = projection.factors["chains_json"].value
        assert chains == ("ethereum", "base") or list(chains) == ["ethereum", "base"]
        if isinstance(chains, tuple):
            pass  # frozen sequence
        else:
            with pytest.raises(TypeError):
                chains.append("solana")  # type: ignore[union-attr]
        assert projection.factors["market_rank"].conflicted is True
        assert projection.factors["market_rank"].value is None
    finally:
        snap_repo.close()
        conn.close()


def test_provider_identity_only_from_mapping_not_evidence_fields() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        # Snapshot is defillama in DB; evidence must not invent source via source_type
        snap = _make_snapshot(source_id="defillama", provider_entity_id="only-map")
        snap_repo.insert_if_absent(snap)
        records = [
            _evidence(
                evidence_id="mapped",
                value="50.00000000",
                source_type="public_market_data",  # misleading field — ignored for provider
                independence_group="defillama-protocols",
                raw_snapshot_ref=f"econ-snapshot:{snap.snapshot_id}",
            )
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        assert projection.factors["tvl_usd"].evidence_id == "mapped"
        assert projection.factors["tvl_usd"].value == "50.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_unmapped_snapshot_excluded_from_provider_dependent_ranking() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_mapped = _make_snapshot(source_id="defillama", provider_entity_id="mapped")
        snap_repo.insert_if_absent(snap_mapped)
        records = [
            _evidence(
                evidence_id="unmapped",
                value="1.00000000",
                raw_snapshot_ref="econ-snapshot:does-not-exist-in-db",
            ),
            _evidence(
                evidence_id="mapped",
                value="2.00000000",
                raw_snapshot_ref=f"econ-snapshot:{snap_mapped.snapshot_id}",
            ),
        ]
        # Same effective_at: unmapped has no provider for ranking → mapped preferred
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        assert projection.factors["tvl_usd"].evidence_id == "mapped"
        assert projection.factors["tvl_usd"].value == "2.00000000"
    finally:
        snap_repo.close()
        conn.close()


def test_nested_json_value_deep_frozen() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap = _make_snapshot(provider_entity_id="json-freeze")
        snap_repo.insert_if_absent(snap)
        records = [
            _evidence(
                evidence_id="chains",
                factor_key="chains_json",
                value={"chains": ["ethereum"], "meta": {"n": 1}},
                value_type="json",
                raw_snapshot_ref=f"econ-snapshot:{snap.snapshot_id}",
            )
        ]
        projection = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        value = projection.factors["chains_json"].value
        assert isinstance(value, MappingProxyType)
        with pytest.raises(TypeError):
            value["new"] = 1  # type: ignore[index]
        nested = value["meta"]
        assert isinstance(nested, MappingProxyType)
        with pytest.raises(TypeError):
            nested["n"] = 2  # type: ignore[index]
    finally:
        snap_repo.close()
        conn.close()


def test_project_economics_data_enabled_false_none_zero_repo_calls() -> None:
    from app.opportunity.economic_resolver import project_economics_data

    evidence_repo = MagicMock()
    snapshot_repo = MagicMock()
    result = project_economics_data(
        "proj-1",
        evidence_repository=evidence_repo,
        snapshot_repository=snapshot_repo,
        direct_available=False,
        now=_NOW,
        enabled=False,
    )
    assert result is None
    evidence_repo.assert_not_called()
    snapshot_repo.assert_not_called()
    evidence_repo.list_evidence.assert_not_called()
    snapshot_repo.source_ids_by_snapshot_id.assert_not_called()


def test_project_economics_data_enabled_true_modes() -> None:
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_resolver import project_economics_data
    from app.opportunity.repository import OpportunityRepository

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    snap_repo = EconomicSnapshotRepository(conn)
    evidence_repo = OpportunityRepository(conn)
    try:
        snap = _make_snapshot(provider_entity_id="mode-test")
        snap_repo.insert_if_absent(snap)
        stored, _ = evidence_repo.add_economic_evidence_if_absent(
            _evidence(
                evidence_id="mode-ev",
                value="42.00000000",
                raw_snapshot_ref=f"econ-snapshot:{snap.snapshot_id}",
            )
        )
        assert stored.evidence_id == "mode-ev"

        # direct_available wins
        direct = project_economics_data(
            "proj-1",
            evidence_repository=evidence_repo,
            snapshot_repository=snap_repo,
            direct_available=True,
            now=_NOW,
            enabled=True,
        )
        assert direct is not None
        assert direct.economics_data_mode == "DIRECT_AVAILABLE"
        assert direct.factors["tvl_usd"].value == "42.00000000"

        # proxy only when at least one usable factor
        proxy = project_economics_data(
            "proj-1",
            evidence_repository=evidence_repo,
            snapshot_repository=snap_repo,
            direct_available=False,
            now=_NOW,
            enabled=True,
        )
        assert proxy is not None
        assert proxy.economics_data_mode == "PROXY_ONLY"

        # unknown when no usable evidence
        unknown = project_economics_data(
            "proj-empty",
            evidence_repository=evidence_repo,
            snapshot_repository=snap_repo,
            direct_available=False,
            now=_NOW,
            enabled=True,
        )
        assert unknown is not None
        assert unknown.economics_data_mode == "UNKNOWN"
        assert all(f.value is None for f in unknown.factors.values())
    finally:
        evidence_repo.close()
        snap_repo.close()
        conn.close()


def test_dto_shapes_and_no_resolve_factor_api() -> None:
    import app.opportunity.economic_resolver as mod
    from app.opportunity.economic_models import (
        EconomicProxyProjection,
        EconomicsDataMode,
        ResolvedEconomicFactor,
    )

    assert not hasattr(mod, "resolve_factor")
    assert EconomicsDataMode  # type alias importable
    factor = ResolvedEconomicFactor(
        factor_key="tvl_usd",
        value=None,
        value_type="string",
        evidence_id=None,
        conflicted=False,
    )
    assert factor.conflicted is False
    projection = EconomicProxyProjection(
        factors=MappingProxyType({"tvl_usd": factor}),
        economics_data_mode="UNKNOWN",
    )
    assert projection.economics_data_mode == "UNKNOWN"


def test_money_tolerance_edge_small_values() -> None:
    """abs(a-b) <= max(1e-8, 1e-8 * max(|a|,|b|)) — small values use absolute 1e-8."""
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_a = _make_snapshot(provider_entity_id="tol-a")
        snap_b = _make_snapshot(provider_entity_id="tol-b", run_id="daily:2026-07-22:tol-b")
        snap_repo.insert_if_absent(snap_a)
        snap_repo.insert_if_absent(snap_b)
        # diff = 5e-9 <= 1e-8 → agree
        records_agree = [
            _evidence(
                evidence_id="s1",
                value="0.00000001",
                independence_group="ga",
                raw_snapshot_ref=f"econ-snapshot:{snap_a.snapshot_id}",
            ),
            _evidence(
                evidence_id="s2",
                value="0.000000015",
                independence_group="gb",
                raw_snapshot_ref=f"econ-snapshot:{snap_b.snapshot_id}",
            ),
        ]
        p = EconomicResolver(snap_repo).resolve("proj-1", records_agree, now=_NOW)
        assert p.factors["tvl_usd"].conflicted is False

        # diff = 2e-8 > 1e-8 → conflict for small values
        records_conflict = [
            _evidence(
                evidence_id="c1",
                value="0.00000001",
                independence_group="ga",
                raw_snapshot_ref=f"econ-snapshot:{snap_a.snapshot_id}",
            ),
            _evidence(
                evidence_id="c2",
                value="0.00000003",
                independence_group="gb",
                raw_snapshot_ref=f"econ-snapshot:{snap_b.snapshot_id}",
            ),
        ]
        p2 = EconomicResolver(snap_repo).resolve("proj-1", records_conflict, now=_NOW)
        assert p2.factors["tvl_usd"].conflicted is True
        assert p2.factors["tvl_usd"].value is None
        assert p2.factors["tvl_usd"].evidence_id is None
    finally:
        snap_repo.close()
        conn.close()


def test_ratio_disagreement_beyond_absolute_tolerance_conflicts() -> None:
    from app.opportunity.economic_resolver import EconomicResolver

    _, conn, snap_repo = _sqlite_snapshot_repo()
    try:
        snap_a = _make_snapshot(provider_entity_id="ratio-a")
        snap_b = _make_snapshot(provider_entity_id="ratio-b", run_id="daily:2026-07-22:ratio-b")
        snap_repo.insert_if_absent(snap_a)
        snap_repo.insert_if_absent(snap_b)
        records = [
            _evidence(
                evidence_id="r1",
                factor_key="price_change_24h_ratio",
                value="0.01000000",
                independence_group="g1",
                source_type="public_market_data",
                raw_snapshot_ref=f"econ-snapshot:{snap_a.snapshot_id}",
            ),
            _evidence(
                evidence_id="r2",
                factor_key="price_change_24h_ratio",
                value="0.02000000",
                independence_group="g2",
                source_type="public_market_data",
                raw_snapshot_ref=f"econ-snapshot:{snap_b.snapshot_id}",
            ),
        ]
        p = EconomicResolver(snap_repo).resolve("proj-1", records, now=_NOW)
        assert p.factors["price_change_24h_ratio"].conflicted is True
        assert p.factors["price_change_24h_ratio"].value is None
    finally:
        snap_repo.close()
        conn.close()
