"""Task 4: opportunity-economic metrics contracts + non-networking EconomicSnapshotWriter.

IMPORTANT: bare Counter.labels() is invalid verification — tests must use
metric_sample_value / metric_label_sets to assert sample values, deltas, and
closed label sets from Prometheus samples.
"""

from __future__ import annotations

import inspect
import sqlite3
from dataclasses import fields, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any, get_type_hints
from unittest.mock import MagicMock, patch

import pytest
from prometheus_client import Counter, Gauge, Histogram

from app.collectors.base import CollectorResult, RawDiscovery
from app.db import DbConnection, init_db
from app.opportunity.economic_models import (
    SCHEMA_VERSION,
    EconomicSnapshotRow,
    NormalizedObservation,
    build_snapshot_id,
    canonical_json_bytes,
    payload_sha256,
)

# ── Metrics contracts ─────────────────────────────────────────────


def test_economic_metric_contracts() -> None:
    """Six metric names/types/labels + sample helpers (not bare .labels())."""
    # bare Counter.labels() is invalid verification — we inspect samples only.
    from app.metrics import (
        OPPORTUNITY_ECONOMIC_EVIDENCE,
        OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
        OPPORTUNITY_ECONOMIC_LAST_SUCCESS,
        OPPORTUNITY_ECONOMIC_OBSERVATIONS,
        OPPORTUNITY_ECONOMIC_RUN_DURATION,
        OPPORTUNITY_ECONOMIC_SNAPSHOTS,
        metric_label_sets,
        metric_sample_value,
        observe_opportunity_economic_duration,
        record_opportunity_economic_evidence,
        record_opportunity_economic_identity,
        record_opportunity_economic_observation,
        record_opportunity_economic_snapshot,
        set_opportunity_economic_last_success,
    )

    expected: list[tuple[Any, type, str, tuple[str, ...]]] = [
        (OPPORTUNITY_ECONOMIC_SNAPSHOTS, Counter, "opportunity_economic_snapshots_total", ("source", "result")),
        (OPPORTUNITY_ECONOMIC_OBSERVATIONS, Counter, "opportunity_economic_observations_total", ("source", "result")),
        (OPPORTUNITY_ECONOMIC_EVIDENCE, Counter, "opportunity_economic_evidence_total", ("source", "result")),
        (
            OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
            Counter,
            "opportunity_economic_identity_resolution_total",
            ("source", "result"),
        ),
        (OPPORTUNITY_ECONOMIC_RUN_DURATION, Histogram, "opportunity_economic_run_duration_seconds", ("source",)),
        (OPPORTUNITY_ECONOMIC_LAST_SUCCESS, Gauge, "opportunity_economic_last_success_unixtime", ("source",)),
    ]
    for metric, cls, name, label_names in expected:
        assert isinstance(metric, cls)
        assert metric._name == name or getattr(metric, "_name", None) == name.removesuffix("_total")
        # prometheus_client Counter stores base name without _total
        assert metric._labelnames == label_names

    # Helper signatures: metric_sample_value(metric, **label_kwargs) -> float
    sig = inspect.signature(metric_sample_value)
    params = list(sig.parameters.values())
    assert params[0].name == "metric"
    assert any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params)
    ret = sig.return_annotation
    assert ret in (float, "float")
    label_sig = inspect.signature(metric_label_sets)
    assert list(label_sig.parameters) == ["metric"]
    # return type documents frozenset[frozenset[tuple[str, str]]]
    assert label_sig.return_annotation is not inspect.Signature.empty

    # Closed vocabularies — illegal source/result raise BEFORE child creation
    with pytest.raises(ValueError):
        record_opportunity_economic_snapshot(source="not-a-source", result="inserted")
    with pytest.raises(ValueError):
        record_opportunity_economic_snapshot(source="defillama", result="rejected_fuzzy_attempt")
    with pytest.raises(ValueError):
        record_opportunity_economic_observation(source="defillama", result="inserted")
    with pytest.raises(ValueError):
        record_opportunity_economic_evidence(source="defillama", result="built")
    with pytest.raises(ValueError):
        record_opportunity_economic_identity(source="defillama", result="emitted")
    with pytest.raises(ValueError):
        observe_opportunity_economic_duration(source="bad", duration_seconds=0.1)
    with pytest.raises(ValueError):
        set_opportunity_economic_last_success(source="bad", unixtime=1.0)

    # Sample value / delta / closed label sets (not bare .labels())
    before = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted")
    record_opportunity_economic_snapshot(source="defillama", result="inserted")
    after = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted")
    assert after - before == 1.0

    before_obs = metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="coingecko", result="built")
    record_opportunity_economic_observation(source="coingecko", result="built")
    assert (
        metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="coingecko", result="built") - before_obs == 1.0
    )

    before_ev = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="cryptorank", result="emitted")
    record_opportunity_economic_evidence(source="cryptorank", result="emitted")
    assert metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="cryptorank", result="emitted") - before_ev == 1.0

    before_id = metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")
    record_opportunity_economic_identity(source="defillama", result="linked")
    assert (
        metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked") - before_id
        == 1.0
    )

    before_count = metric_sample_value(OPPORTUNITY_ECONOMIC_RUN_DURATION, source="defillama")
    observe_opportunity_economic_duration(source="defillama", duration_seconds=0.25)
    after_count = metric_sample_value(OPPORTUNITY_ECONOMIC_RUN_DURATION, source="defillama")
    assert after_count - before_count == 1.0  # histogram _count delta

    set_opportunity_economic_last_success(source="defillama", unixtime=1_721_664_000.0)
    assert metric_sample_value(OPPORTUNITY_ECONOMIC_LAST_SUCCESS, source="defillama") == 1_721_664_000.0

    # Closed label sets from samples
    snap_sets = metric_label_sets(OPPORTUNITY_ECONOMIC_SNAPSHOTS)
    assert isinstance(snap_sets, frozenset)
    for label_set in snap_sets:
        assert isinstance(label_set, frozenset)
        as_dict = dict(label_set)
        if "source" in as_dict:
            assert as_dict["source"] in {"defillama", "coingecko", "cryptorank"}
        if "result" in as_dict:
            assert as_dict["result"] in {
                "inserted",
                "duplicate",
                "schema_invalid",
                "skipped_flag_off",
            }
            assert as_dict["result"] != "rejected_fuzzy_attempt"
            assert "project" not in as_dict
            assert "symbol" not in as_dict
            assert "id" not in as_dict

    # Explicitly document: bare labels() creating a child is NOT verification
    # (would not prove sample value or closed label set).
    child = OPPORTUNITY_ECONOMIC_SNAPSHOTS.labels(source="coingecko", result="duplicate")
    assert child is not None  # existence alone is invalid verification


# ── Fixtures / helpers for writer tests ───────────────────────────


def _sqlite_repo():
    from app.opportunity.economic_repository import EconomicSnapshotRepository

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return raw, conn, EconomicSnapshotRepository(conn)


def _discovery(
    *,
    source_id: str = "defillama",
    raw_id: str = "raw-example-1",
    name: str = "Example Protocol",
    url: str | None = "https://api.llama.fi/protocol/example?key=secret#frag",
    raw_data: dict[str, Any] | None = None,
) -> RawDiscovery:
    body = (
        raw_data
        if raw_data is not None
        else {
            "tvl": 1_000_000,
            "change_7d": 0.05,
            "change_7d_unit": "ratio",
            "chains": ["Ethereum", "Arbitrum"],
            "no_token_yet": False,
            "extra_noise": "ignored",
        }
    )
    return RawDiscovery(
        source_id=source_id,
        raw_id=raw_id,
        name=name,
        url=url,
        sector="DeFi",
        stage="mainnet",
        raw_data=body,
    )


def _result(
    items: list[RawDiscovery] | None = None,
    *,
    source_id: str = "defillama",
    finished_at: datetime | None = None,
) -> CollectorResult:
    r = CollectorResult(source_id=source_id, items=items or [])
    r.finished_at = finished_at
    return r


def _make_snapshot_row(
    *,
    run_id: str = "daily:2026-07-22:defillama",
    source_id: str = "defillama",
    dedup_key: str = "protocol:example",
    provider_entity_id: str = "raw-example-1",
    payload: dict[str, Any] | None = None,
    source_url: str = "https://api.llama.fi/protocol/example",
    collected_at: datetime | None = None,
    schema_version: str = SCHEMA_VERSION,
    payload_sha256_override: str | None = None,
) -> EconomicSnapshotRow:
    body = (
        payload
        if payload is not None
        else {
            "tvl": 1_000_000,
            "change_7d": 0.05,
            "change_7d_unit": "ratio",
            "chains": ["Ethereum", "Arbitrum"],
            "no_token_yet": False,
        }
    )
    digest = payload_sha256_override if payload_sha256_override is not None else payload_sha256(body)
    snapshot_id = build_snapshot_id(
        run_id=run_id,
        source_id=source_id,
        provider_entity_id=provider_entity_id,
        payload_sha256_hex=digest if payload_sha256_override is None else payload_sha256(body),
    )
    # When testing hash mismatch, keep snapshot_id from real payload but wrong stored hash
    if payload_sha256_override is not None:
        digest = payload_sha256_override
        snapshot_id = build_snapshot_id(
            run_id=run_id,
            source_id=source_id,
            provider_entity_id=provider_entity_id,
            payload_sha256_hex=payload_sha256(body),
        )
    return EconomicSnapshotRow(
        snapshot_id=snapshot_id,
        schema_version=schema_version,  # type: ignore[arg-type]
        run_id=run_id,
        source_id=source_id,
        dedup_key=dedup_key,
        provider_entity_id=provider_entity_id,
        payload_sha256=digest,
        payload_json=body,
        source_url=source_url,
        collected_at=collected_at or datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )


# ── Writer process contract ───────────────────────────────────────


def test_writer_process_contract() -> None:
    """process(enabled) contract: non-networking, rebuild after insert/duplicate, isolation."""
    from app.metrics import (
        OPPORTUNITY_ECONOMIC_EVIDENCE,
        OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION,
        OPPORTUNITY_ECONOMIC_LAST_SUCCESS,
        OPPORTUNITY_ECONOMIC_OBSERVATIONS,
        OPPORTUNITY_ECONOMIC_RUN_DURATION,
        OPPORTUNITY_ECONOMIC_SNAPSHOTS,
        metric_sample_value,
    )
    from app.opportunity.economic_normalizers import PROVIDER_RAW_FIELD_KEYS, canonical_provider_payload
    from app.opportunity.economic_writer import (
        EconomicSnapshotWriter,
        EconomicWriteSummary,
        observation_from_snapshot,
        utc_now,
    )

    # Summary exact fields + types
    assert is_dataclass(EconomicWriteSummary)
    assert EconomicWriteSummary.__dataclass_params__.frozen is True  # type: ignore[attr-defined]
    field_names = [f.name for f in fields(EconomicWriteSummary)]
    assert field_names == [
        "source_id",
        "run_id",
        "observations",
        "snapshots_inserted",
        "snapshots_duplicate",
        "schema_invalid",
        "skipped_flag_off",
    ]
    hints = get_type_hints(EconomicWriteSummary)
    assert hints["source_id"] is str
    assert hints["run_id"] is str
    assert hints["observations"] == tuple[NormalizedObservation, ...]
    assert hints["snapshots_inserted"] is int
    assert hints["snapshots_duplicate"] is int
    assert hints["schema_invalid"] is int
    assert hints["skipped_flag_off"] is int

    # process signature exact; no write method
    sig = inspect.signature(EconomicSnapshotWriter.process)
    params = list(sig.parameters)
    assert params == ["self", "result", "run_id", "enabled"]
    assert sig.parameters["run_id"].kind == inspect.Parameter.KEYWORD_ONLY
    assert sig.parameters["enabled"].kind == inspect.Parameter.KEYWORD_ONLY
    assert not hasattr(EconomicSnapshotWriter, "write") or not callable(getattr(EconomicSnapshotWriter, "write", None))
    assert not hasattr(EconomicSnapshotWriter, "write")

    # utc_now returns UTC aware
    now = utc_now()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)

    fixed_now = datetime(2026, 7, 22, 15, 30, 0, tzinfo=UTC)

    # ── enabled=False: zero repo, zero reconstruction, counts ──
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        items = [_discovery(raw_id="r1", name="A"), _discovery(raw_id="r2", name="B")]
        result = _result(items, finished_at=fixed_now)

        with patch(
            "app.opportunity.economic_writer.observation_from_snapshot",
            wraps=observation_from_snapshot,
        ) as recon_spy:
            repo_spy = MagicMock(wraps=repo)
            writer_off = EconomicSnapshotWriter(repo_spy, now_factory=lambda: fixed_now)
            before_skip = metric_sample_value(
                OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="skipped_flag_off"
            )
            before_obs_skip = metric_sample_value(
                OPPORTUNITY_ECONOMIC_OBSERVATIONS,
                source="defillama",
                result="skipped_no_snapshot",
            )
            before_ev = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
            before_id = metric_sample_value(
                OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked"
            )

            summary = writer_off.process(result, run_id="daily:2026-07-22:defillama", enabled=False)

            assert summary.source_id == "defillama"
            assert summary.run_id == "daily:2026-07-22:defillama"
            assert summary.observations == ()
            assert summary.snapshots_inserted == 0
            assert summary.snapshots_duplicate == 0
            assert summary.schema_invalid == 0
            assert summary.skipped_flag_off == 2
            assert repo_spy.insert_if_absent.call_count == 0
            assert repo_spy.get.call_count == 0
            assert recon_spy.call_count == 0
            assert (
                metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="skipped_flag_off")
                - before_skip
                == 2.0
            )
            assert (
                metric_sample_value(
                    OPPORTUNITY_ECONOMIC_OBSERVATIONS,
                    source="defillama",
                    result="skipped_no_snapshot",
                )
                - before_obs_skip
                == 2.0
            )
            # No evidence / identity metrics from writer
            assert metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted") == before_ev
            assert (
                metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")
                == before_id
            )
    finally:
        repo.close()
        conn.close()

    # ── enabled=True: insert + built observation; payload whitelist ──
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        item = _discovery()
        result = _result([item], finished_at=fixed_now)

        before_ins = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted")
        before_built = metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="defillama", result="built")
        before_dur = metric_sample_value(OPPORTUNITY_ECONOMIC_RUN_DURATION, source="defillama")
        before_ev = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        before_id = metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")

        with patch(
            "app.opportunity.economic_writer.observation_from_snapshot",
            wraps=observation_from_snapshot,
        ) as recon_spy:
            summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)

        assert summary.snapshots_inserted == 1
        assert summary.snapshots_duplicate == 0
        assert summary.schema_invalid == 0
        assert summary.skipped_flag_off == 0
        assert len(summary.observations) == 1
        obs = summary.observations[0]
        assert isinstance(obs, NormalizedObservation)
        assert obs.source_id == "defillama"
        assert obs.provider_entity_id == item.raw_id
        assert obs.dedup_key == item.dedup_key
        assert obs.source_url == "https://api.llama.fi/protocol/example"
        assert "?" not in obs.source_url and "#" not in obs.source_url
        assert recon_spy.call_count == 1

        stored = repo.get(obs.snapshot_id)
        assert stored is not None
        # payload_json only provider-native whitelist keys that were present
        payload_dict = dict(stored.payload_json)
        allowed = PROVIDER_RAW_FIELD_KEYS["defillama"]
        assert set(payload_dict.keys()) <= set(allowed)
        assert "extra_noise" not in payload_dict
        assert "url" not in payload_dict
        expected_payload = canonical_provider_payload("defillama", item.raw_data)
        # Frozen payload may use tuples for arrays; compare via canonical bytes.
        assert canonical_json_bytes(payload_dict) == canonical_json_bytes(expected_payload)
        assert stored.payload_sha256 == payload_sha256(expected_payload)
        assert stored.payload_sha256 == payload_sha256(payload_dict)

        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="inserted") - before_ins
            == 1.0
        )
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_OBSERVATIONS, source="defillama", result="built") - before_built
            == 1.0
        )
        assert metric_sample_value(OPPORTUNITY_ECONOMIC_RUN_DURATION, source="defillama") - before_dur == 1.0
        # last-success set when ≥1 observation
        assert metric_sample_value(OPPORTUNITY_ECONOMIC_LAST_SUCCESS, source="defillama") > 0
        assert metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted") == before_ev
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_IDENTITY_RESOLUTION, source="defillama", result="linked")
            == before_id
        )

        # duplicate path: same run/items again → duplicate + built
        before_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
        summary2 = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary2.snapshots_inserted == 0
        assert summary2.snapshots_duplicate == 1
        assert len(summary2.observations) == 1
        assert summary2.observations[0].snapshot_id == obs.snapshot_id
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate") - before_dup
            == 1.0
        )
    finally:
        repo.close()
        conn.close()

    # ── now_factory fallback when finished_at is None; UTC normalization ──
    raw, conn, repo = _sqlite_repo()
    try:
        naive = datetime(2026, 7, 22, 10, 0, 0)  # naive
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: naive)
        item = _discovery(raw_id="naive-1", name="Naive Protocol")
        result = _result([item], finished_at=None)
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary.snapshots_inserted == 1
        obs = summary.observations[0]
        assert obs.collected_at.tzinfo is not None
        assert obs.collected_at == naive.replace(tzinfo=UTC)

        # aware non-UTC → convert to UTC
        eastern = timezone(timedelta(hours=-5))
        aware_non_utc = datetime(2026, 7, 22, 10, 0, 0, tzinfo=eastern)
        writer2 = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        item2 = _discovery(raw_id="aware-1", name="Aware Protocol")
        result2 = _result([item2], finished_at=aware_non_utc)
        summary2 = writer2.process(result2, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary2.observations[0].collected_at == aware_non_utc.astimezone(UTC)
    finally:
        repo.close()
        conn.close()

    # ── per-row isolation: bad URL only invalidates that row ──
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        good = _discovery(raw_id="good-1", name="Good Proto")
        bad = _discovery(
            raw_id="bad-1",
            name="Bad Proto",
            url="ftp://not-allowed.example/x",
        )
        result = _result([bad, good], finished_at=fixed_now)
        before_inv = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="schema_invalid")
        summary = writer.process(result, run_id="daily:2026-07-22:defillama", enabled=True)
        assert summary.schema_invalid == 1
        assert summary.snapshots_inserted == 1
        assert len(summary.observations) == 1
        assert summary.observations[0].provider_entity_id == "good-1"
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="schema_invalid")
            - before_inv
            == 1.0
        )
    finally:
        repo.close()
        conn.close()

    # ── repo exception / content conflict: not schema_invalid ──
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        # First good insert
        good = _discovery(raw_id="keep-1", name="Keep Proto")
        writer.process(_result([good], finished_at=fixed_now), run_id="run-keep", enabled=True)
        count_before = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]

        # Force content conflict on next insert via patched insert_if_absent
        from app.opportunity.economic_repository import EconomicSnapshotContentConflict

        def boom(snapshot):
            raise EconomicSnapshotContentConflict("forced conflict")

        with patch.object(repo, "insert_if_absent", side_effect=boom):
            before_inv = metric_sample_value(
                OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="schema_invalid"
            )
            before_skip_obs = metric_sample_value(
                OPPORTUNITY_ECONOMIC_OBSERVATIONS,
                source="defillama",
                result="skipped_no_snapshot",
            )
            conflict_item = _discovery(raw_id="conflict-1", name="Conflict Proto")
            summary = writer.process(
                _result([conflict_item], finished_at=fixed_now),
                run_id="run-conflict",
                enabled=True,
            )
            assert summary.schema_invalid == 0
            assert summary.snapshots_inserted == 0
            assert summary.observations == ()
            assert (
                metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="schema_invalid")
                == before_inv
            )
            assert (
                metric_sample_value(
                    OPPORTUNITY_ECONOMIC_OBSERVATIONS,
                    source="defillama",
                    result="skipped_no_snapshot",
                )
                - before_skip_obs
                == 1.0
            )
        # Prior successful snapshot retained
        count_after = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count_after == count_before
    finally:
        repo.close()
        conn.close()

    # ── empty items legal ──
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)
        summary = writer.process(
            _result([], finished_at=fixed_now),
            run_id="daily:2026-07-22:defillama",
            enabled=True,
        )
        assert summary.observations == ()
        assert summary.snapshots_inserted == 0
        assert summary.snapshots_duplicate == 0
        assert summary.schema_invalid == 0
        assert summary.skipped_flag_off == 0
    finally:
        repo.close()
        conn.close()


# ── observation_from_snapshot reconstruction contracts ────────────


def test_observation_from_snapshot_schema_version_mismatch() -> None:
    from app.opportunity.economic_writer import (
        EconomicReconstructionError,
        observation_from_snapshot,
    )

    # Bypass pydantic Literal via model_construct for mismatch fixture
    body = {"tvl": 1.0, "change_7d": 0.1, "change_7d_unit": "ratio"}
    digest = payload_sha256(body)
    snap = EconomicSnapshotRow.model_construct(
        snapshot_id="sid",
        schema_version="wrong-schema-v0",
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e",
        payload_sha256=digest,
        payload_json=body,
        source_url="https://api.llama.fi/protocol/x",
        collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(EconomicReconstructionError):
        observation_from_snapshot(snap)


def test_observation_from_snapshot_hash_mismatch() -> None:
    from app.opportunity.economic_writer import (
        EconomicReconstructionError,
        observation_from_snapshot,
    )

    body = {"tvl": 1.0, "change_7d": 0.1, "change_7d_unit": "ratio"}
    snap = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="run",
            source_id="defillama",
            provider_entity_id="e",
            payload_sha256_hex=payload_sha256(body),
        ),
        schema_version=SCHEMA_VERSION,
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e",
        payload_sha256="0" * 64,  # wrong hash
        payload_json=body,
        source_url="https://api.llama.fi/protocol/x",
        collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(EconomicReconstructionError):
        observation_from_snapshot(snap)


def test_observation_from_snapshot_defillama_invalid_change_7d_unit() -> None:
    from app.opportunity.economic_writer import (
        EconomicReconstructionError,
        observation_from_snapshot,
    )

    body = {"tvl": 1.0, "change_7d": 0.1, "change_7d_unit": "percent"}
    digest = payload_sha256(body)
    snap = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="run",
            source_id="defillama",
            provider_entity_id="e",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e",
        payload_sha256=digest,
        payload_json=body,
        source_url="https://api.llama.fi/protocol/x",
        collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )
    with pytest.raises(EconomicReconstructionError):
        observation_from_snapshot(snap)


def test_observation_from_snapshot_source_url_sanitize() -> None:
    from app.opportunity.economic_writer import observation_from_snapshot

    body = {"tvl": 1.0, "change_7d": 0.1, "change_7d_unit": "ratio"}
    digest = payload_sha256(body)
    snap = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="run",
            source_id="defillama",
            provider_entity_id="e",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="run",
        source_id="defillama",
        dedup_key="k",
        provider_entity_id="e",
        payload_sha256=digest,
        payload_json=body,
        source_url="https://api.llama.fi/protocol/x?token=secret#section",
        collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )
    obs = observation_from_snapshot(snap)
    assert obs.source_url == "https://api.llama.fi/protocol/x"
    assert all(f.source_url == obs.source_url for f in obs.factors)


def test_observation_from_snapshot_reconstruction_success_fields() -> None:
    from app.opportunity.economic_writer import observation_from_snapshot

    body = {
        "tvl": 1_000_000,
        "change_7d": 0.05,
        "change_7d_unit": "ratio",
        "chains": ["Ethereum"],
        "no_token_yet": True,
    }
    digest = payload_sha256(body)
    snap = EconomicSnapshotRow(
        snapshot_id=build_snapshot_id(
            run_id="run",
            source_id="defillama",
            provider_entity_id="entity-1",
            payload_sha256_hex=digest,
        ),
        schema_version=SCHEMA_VERSION,
        run_id="run",
        source_id="defillama",
        dedup_key="protocol:example",
        provider_entity_id="entity-1",
        payload_sha256=digest,
        payload_json=body,
        source_url="https://api.llama.fi/protocol/example",
        collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
    )
    obs = observation_from_snapshot(snap)
    assert obs.snapshot_id == snap.snapshot_id
    assert obs.source_id == snap.source_id
    assert obs.dedup_key == snap.dedup_key
    assert obs.provider_entity_id == snap.provider_entity_id
    assert obs.collected_at == snap.collected_at
    assert isinstance(obs.factors, tuple)
    assert len(obs.factors) >= 1


def test_reconstruction_per_row_isolation_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad reconstruction row does not emit Evidence and does not block good built row."""
    from app.metrics import (
        OPPORTUNITY_ECONOMIC_EVIDENCE,
        metric_sample_value,
    )
    from app.opportunity import economic_writer as writer_mod
    from app.opportunity.economic_writer import EconomicSnapshotWriter, observation_from_snapshot

    raw, conn, repo = _sqlite_repo()
    try:
        fixed_now = datetime(2026, 7, 22, 15, 30, 0, tzinfo=UTC)
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: fixed_now)

        good = _discovery(raw_id="iso-good", name="Iso Good")
        bad = _discovery(raw_id="iso-bad", name="Iso Bad")

        real_recon = observation_from_snapshot
        call_log: list[str] = []

        def selective_recon(snapshot, *, normalizer=None):
            call_log.append(snapshot.provider_entity_id)
            if snapshot.provider_entity_id == "iso-bad":
                raise ValueError("forced reconstruction failure")
            if normalizer is None:
                return real_recon(snapshot)
            return real_recon(snapshot, normalizer=normalizer)

        monkeypatch.setattr(writer_mod, "observation_from_snapshot", selective_recon)

        before_ev = metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted")
        summary = writer.process(
            _result([bad, good], finished_at=fixed_now),
            run_id="daily:2026-07-22:defillama",
            enabled=True,
        )
        # Both rows may have been inserted; bad recon isolated from observations
        assert summary.snapshots_inserted + summary.snapshots_duplicate >= 1
        assert all(o.provider_entity_id != "iso-bad" for o in summary.observations)
        assert any(o.provider_entity_id == "iso-good" for o in summary.observations)
        # No Evidence metrics
        assert metric_sample_value(OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="emitted") == before_ev
        # Bad snapshot row retained if insert succeeded before recon failure
        rows = raw.execute("SELECT provider_entity_id FROM opportunity_economic_snapshots").fetchall()
        entity_ids = {r["provider_entity_id"] for r in rows}
        assert "iso-good" in entity_ids
    finally:
        repo.close()
        conn.close()


def test_writer_retry_later_finished_at_is_duplicate_preserves_collected_at() -> None:
    """Same run/source/entity/payload with later finished_at is duplicate, not conflict.

    Observation rebuilt from the persisted row keeps the original collected_at.
    """
    from app.metrics import OPPORTUNITY_ECONOMIC_SNAPSHOTS, metric_sample_value
    from app.opportunity.economic_writer import EconomicSnapshotWriter

    first_finished = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    later_finished = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)
    raw, conn, repo = _sqlite_repo()
    try:
        writer = EconomicSnapshotWriter(repo, now_factory=lambda: first_finished)
        item = _discovery(raw_id="retry-1", name="Retry Proto")
        run_id = "daily:2026-07-22:defillama"

        summary1 = writer.process(
            _result([item], finished_at=first_finished),
            run_id=run_id,
            enabled=True,
        )
        assert summary1.snapshots_inserted == 1
        assert summary1.snapshots_duplicate == 0
        assert len(summary1.observations) == 1
        first_obs = summary1.observations[0]
        assert first_obs.collected_at == first_finished
        stored_after_first = repo.get(first_obs.snapshot_id)
        assert stored_after_first is not None
        assert stored_after_first.collected_at == first_finished

        before_dup = metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate")
        summary2 = writer.process(
            _result([item], finished_at=later_finished),
            run_id=run_id,
            enabled=True,
        )
        assert summary2.snapshots_inserted == 0
        assert summary2.snapshots_duplicate == 1
        assert summary2.schema_invalid == 0
        assert len(summary2.observations) == 1
        second_obs = summary2.observations[0]
        assert second_obs.snapshot_id == first_obs.snapshot_id
        assert second_obs.collected_at == first_finished
        assert second_obs.collected_at != later_finished
        assert (
            metric_sample_value(OPPORTUNITY_ECONOMIC_SNAPSHOTS, source="defillama", result="duplicate") - before_dup
            == 1.0
        )

        stored = repo.get(first_obs.snapshot_id)
        assert stored is not None
        assert stored.collected_at == first_finished
        count = raw.execute("SELECT COUNT(*) FROM opportunity_economic_snapshots").fetchone()[0]
        assert count == 1
    finally:
        repo.close()
        conn.close()
