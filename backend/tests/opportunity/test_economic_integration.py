"""Task 7: pure economic integration helpers + process_persisted_collection."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, call, patch
from uuid import UUID

import pytest

from app.collectors.base import CollectorResult, RawDiscovery
from app.config import Settings
from app.db import DbConnection, init_db
from app.opportunity.economic_models import (
    NormalizedFactor,
    NormalizedObservation,
)
from app.opportunity.economic_writer import EconomicWriteSummary

# ── helpers ───────────────────────────────────────────────────────


def _settings(**overrides: Any) -> Settings:
    base = dict(
        opportunity_economic_snapshot_enabled=False,
        opportunity_economic_source_defillama_enabled=False,
        opportunity_economic_source_coingecko_enabled=False,
        opportunity_economic_source_cryptorank_enabled=False,
        opportunity_economic_evidence_emit_enabled=False,
        opportunity_economic_resolver_enabled=False,
        defillama_enabled=True,
        coingecko_enabled=True,
        cryptorank_enabled=True,
    )
    base.update(overrides)
    return Settings(_env_file=None, **base)


def _discovery(
    *,
    source_id: str = "defillama",
    raw_id: str = "raw-example-1",
    name: str = "Example Protocol",
    sector: str | None = "DeFi",
    url: str | None = "https://api.llama.fi/protocol/example",
    raw_data: dict[str, Any] | None = None,
) -> RawDiscovery:
    body = raw_data if raw_data is not None else {
        "tvl": 1_000_000,
        "change_7d": 0.05,
        "change_7d_unit": "ratio",
        "chains": ["Ethereum", "Arbitrum"],
        "no_token_yet": False,
    }
    return RawDiscovery(
        source_id=source_id,
        raw_id=raw_id,
        name=name,
        url=url,
        sector=sector,
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
    r.finished_at = finished_at or datetime(2026, 7, 22, 15, 30, tzinfo=UTC)
    r.status = "success"
    return r


def _obs(
    *,
    snapshot_id: str = "snap-1",
    source_id: str = "defillama",
    dedup_key: str = "protocol:example",
) -> NormalizedObservation:
    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    return NormalizedObservation(
        snapshot_id=snapshot_id,
        source_id=source_id,
        dedup_key=dedup_key,
        provider_entity_id="entity-1",
        factors=(
            NormalizedFactor(
                factor_key="tvl_usd",
                value="1000000.00000000",
                value_type="string",
                unit=None,
                source_type="public_aggregator",
                source_grade="C",
                verification_status="verified",
                independence_group="defillama-protocols",
                source_url="https://api.llama.fi/protocol/example",
                observed_at=now,
                expires_at=now + timedelta(hours=48),
            ),
        ),
        collected_at=now,
        source_url="https://api.llama.fi/protocol/example",
    )


def _summary(
    observations: tuple[NormalizedObservation, ...] = (),
    *,
    source_id: str = "defillama",
    run_id: str = "daily:2026-07-22:defillama",
) -> EconomicWriteSummary:
    return EconomicWriteSummary(
        source_id=source_id,
        run_id=run_id,
        observations=observations,
        snapshots_inserted=len(observations),
        snapshots_duplicate=0,
        schema_invalid=0,
        skipped_flag_off=0,
    )


def _sqlite_stack():
    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    return raw, conn


# ── ECONOMIC_SOURCES / run ids / gates ────────────────────────────


def test_economic_sources_membership() -> None:
    from app.opportunity.economic_integration import ECONOMIC_SOURCES

    assert frozenset({"defillama", "coingecko", "cryptorank"}) == ECONOMIC_SOURCES
    assert "github" not in ECONOMIC_SOURCES
    assert isinstance(ECONOMIC_SOURCES, frozenset)


def test_daily_run_id_form_stability_and_cross_date() -> None:
    from app.opportunity.economic_integration import daily_run_id

    t1 = datetime(2026, 7, 22, 1, 0, tzinfo=UTC)
    t2 = datetime(2026, 7, 22, 23, 59, tzinfo=UTC)
    t3 = datetime(2026, 7, 23, 0, 0, tzinfo=UTC)

    assert daily_run_id("defillama", t1) == "daily:2026-07-22:defillama"
    assert daily_run_id("defillama", t2) == "daily:2026-07-22:defillama"
    assert daily_run_id("defillama", t1) == daily_run_id("defillama", t2)
    assert daily_run_id("defillama", t3) == "daily:2026-07-23:defillama"
    assert daily_run_id("defillama", t1) != daily_run_id("defillama", t3)
    assert daily_run_id("coingecko", t1) == "daily:2026-07-22:coingecko"

    # Non-UTC offset still uses UTC calendar date
    offset = timezone(timedelta(hours=5))
    local = datetime(2026, 7, 23, 2, 0, tzinfo=offset)  # 2026-07-22 21:00 UTC
    assert daily_run_id("defillama", local) == "daily:2026-07-22:defillama"


def test_manual_run_id_exact_form_and_uniqueness() -> None:
    from app.opportunity.economic_integration import manual_run_id

    fixed = UUID("550e8400-e29b-41d4-a716-446655440000")
    assert manual_run_id(uuid_factory=lambda: fixed) == (
        "manual:550e8400-e29b-41d4-a716-446655440000"
    )

    a = manual_run_id()
    b = manual_run_id()
    assert a.startswith("manual:")
    assert b.startswith("manual:")
    assert a != b
    assert not a.startswith("daily:")
    assert a != "daily:2026-07-22:defillama"


@pytest.mark.parametrize(
    ("source_id", "snap", "src_flag", "provider", "expected"),
    [
        ("defillama", True, True, True, True),
        ("defillama", False, True, True, False),
        ("defillama", True, False, True, False),
        ("defillama", True, True, False, False),
        ("coingecko", True, True, True, True),
        ("coingecko", False, True, True, False),
        ("coingecko", True, False, True, False),
        ("coingecko", True, True, False, False),
        ("cryptorank", True, True, True, True),
        ("cryptorank", False, True, True, False),
        ("cryptorank", True, False, True, False),
        ("cryptorank", True, True, False, False),
        ("github", True, True, True, False),
        ("unknown", True, True, True, False),
    ],
)
def test_economic_source_enabled_triple_conjunction(
    source_id: str,
    snap: bool,
    src_flag: bool,
    provider: bool,
    expected: bool,
) -> None:
    from app.opportunity.economic_integration import economic_source_enabled

    kwargs: dict[str, Any] = {
        "opportunity_economic_snapshot_enabled": snap,
        "opportunity_economic_source_defillama_enabled": False,
        "opportunity_economic_source_coingecko_enabled": False,
        "opportunity_economic_source_cryptorank_enabled": False,
        "defillama_enabled": True,
        "coingecko_enabled": True,
        "cryptorank_enabled": True,
    }
    if source_id == "defillama":
        kwargs["opportunity_economic_source_defillama_enabled"] = src_flag
        kwargs["defillama_enabled"] = provider
    elif source_id == "coingecko":
        kwargs["opportunity_economic_source_coingecko_enabled"] = src_flag
        kwargs["coingecko_enabled"] = provider
    elif source_id == "cryptorank":
        kwargs["opportunity_economic_source_cryptorank_enabled"] = src_flag
        kwargs["cryptorank_enabled"] = provider
    else:
        # unsupported: still set all source flags true so only unsupported check matters
        kwargs["opportunity_economic_source_defillama_enabled"] = True
        kwargs["opportunity_economic_source_coingecko_enabled"] = True
        kwargs["opportunity_economic_source_cryptorank_enabled"] = True

    settings_obj = _settings(**kwargs)
    assert economic_source_enabled(source_id, settings_obj) is expected


# ── process_persisted_collection ──────────────────────────────────


def test_process_gate_false_and_unsupported_zero_calls() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    writer = MagicMock()
    emitter = MagicMock()
    result = _result()

    # all flags false
    out = process_persisted_collection(
        result,
        run_id="daily:2026-07-22:defillama",
        writer=writer,
        emitter=emitter,
        settings_obj=_settings(),
    )
    assert out is None
    writer.process.assert_not_called()
    emitter.emit.assert_not_called()

    # unsupported source even if flags on
    github = _result(source_id="github")
    out2 = process_persisted_collection(
        github,
        run_id="daily:2026-07-22:github",
        writer=writer,
        emitter=emitter,
        settings_obj=_settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
        ),
    )
    assert out2 is None
    writer.process.assert_not_called()
    emitter.emit.assert_not_called()


def test_process_gate_true_writer_once_then_same_emitter_per_observation() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    o1 = _obs(snapshot_id="s1")
    o2 = _obs(snapshot_id="s2", dedup_key="protocol:other")
    summary = _summary((o1, o2))
    writer = MagicMock()
    writer.process.return_value = summary
    emitter = MagicMock()
    emitter.emit.return_value = SimpleNamespace(skipped_flag_off=0, emitted=1)

    result = _result([_discovery(), _discovery(raw_id="r2", name="Other")])
    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
        opportunity_economic_evidence_emit_enabled=True,
    )
    out = process_persisted_collection(
        result,
        run_id="daily:2026-07-22:defillama",
        writer=writer,
        emitter=emitter,
        settings_obj=settings_obj,
    )
    assert out is summary
    writer.process.assert_called_once_with(
        result, run_id="daily:2026-07-22:defillama", enabled=True
    )
    assert emitter.emit.call_count == 2
    assert emitter.emit.call_args_list == [
        call(o1, enabled=True),
        call(o2, enabled=True),
    ]


def test_evidence_flag_false_still_writes_then_emit_enabled_false() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    o1 = _obs()
    summary = _summary((o1,))
    writer = MagicMock()
    writer.process.return_value = summary
    emitter = MagicMock()
    emitter.emit.return_value = SimpleNamespace(
        skipped_flag_off=1, emitted=0, duplicates=0, unlinked=0, conflicts=0
    )

    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
        opportunity_economic_evidence_emit_enabled=False,
    )
    result = _result([_discovery()])
    out = process_persisted_collection(
        result,
        run_id="daily:2026-07-22:defillama",
        writer=writer,
        emitter=emitter,
        settings_obj=settings_obj,
    )
    assert out is summary
    writer.process.assert_called_once_with(
        result, run_id="daily:2026-07-22:defillama", enabled=True
    )
    assert writer.process.call_args.kwargs["enabled"] is True
    emitter.emit.assert_called_once_with(o1, enabled=False)


def test_writer_failure_returns_none_zero_emitter() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    writer = MagicMock()
    writer.process.side_effect = RuntimeError("writer boom")
    emitter = MagicMock()
    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
    )
    with patch("app.opportunity.economic_integration.logger") as log:
        out = process_persisted_collection(
            _result([_discovery()]),
            run_id="daily:2026-07-22:defillama",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
    assert out is None
    emitter.emit.assert_not_called()
    # bounded credential-free log (no Authorization/token secrets)
    assert log.warning.called or log.error.called
    log_calls = str(log.method_calls)
    assert "Authorization" not in log_calls
    assert "Bearer" not in log_calls
    assert "api_key" not in log_calls.lower() or "api_key" not in log_calls


def test_writer_none_summary_zero_emitter() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    writer = MagicMock()
    writer.process.return_value = None
    emitter = MagicMock()
    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
    )
    out = process_persisted_collection(
        _result([_discovery()]),
        run_id="daily:2026-07-22:defillama",
        writer=writer,
        emitter=emitter,
        settings_obj=settings_obj,
    )
    assert out is None
    emitter.emit.assert_not_called()


def test_emitter_failure_isolates_and_continues_reuses_same_emitter() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    o1 = _obs(snapshot_id="s1")
    o2 = _obs(snapshot_id="s2", dedup_key="protocol:b")
    o3 = _obs(snapshot_id="s3", dedup_key="protocol:c")
    summary = _summary((o1, o2, o3))
    writer = MagicMock()
    writer.process.return_value = summary
    emitter = MagicMock()
    emitter.emit.side_effect = [
        RuntimeError("emit fail"),
        SimpleNamespace(emitted=1, skipped_flag_off=0),
        SimpleNamespace(emitted=1, skipped_flag_off=0),
    ]
    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
        opportunity_economic_evidence_emit_enabled=True,
    )
    with patch("app.opportunity.economic_integration.logger") as log:
        out = process_persisted_collection(
            _result([_discovery()]),
            run_id="daily:2026-07-22:defillama",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
    assert out is summary
    assert emitter.emit.call_count == 3
    assert emitter.emit.call_args_list[0] == call(o1, enabled=True)
    assert emitter.emit.call_args_list[1] == call(o2, enabled=True)
    assert emitter.emit.call_args_list[2] == call(o3, enabled=True)
    assert log.warning.called or log.error.called


def test_process_never_collects_persists_or_http() -> None:
    from app.opportunity.economic_integration import process_persisted_collection

    o1 = _obs()
    writer = MagicMock()
    writer.process.return_value = _summary((o1,))
    emitter = MagicMock()
    settings_obj = _settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
        opportunity_economic_evidence_emit_enabled=True,
    )
    with (
        patch("httpx.Client") as http_client,
        patch("httpx.AsyncClient") as http_async,
        patch("urllib.request.urlopen") as urlopen,
    ):
        process_persisted_collection(
            _result([_discovery()]),
            run_id="r1",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
    http_client.assert_not_called()
    http_async.assert_not_called()
    urlopen.assert_not_called()
    # no collect/persist methods on integration surface
    assert not hasattr(process_persisted_collection, "collect")


def test_real_linked_identity_immediate_evidence_and_unlinked_retains_snapshot() -> None:
    """Existing exact raw identity + authoritative project → immediate Evidence.

    Unlinked identity retains snapshot with zero Evidence.
    """
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_integration import process_persisted_collection
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    raw, conn = _sqlite_stack()
    try:
        # Authoritative project + linked raw row matching discovery dedup
        item = _discovery(name="Linked Protocol", sector="DeFi")
        project_id = item.project_id
        dedup = item.dedup_key
        conn.execute(
            "INSERT INTO projects (id, name, source) VALUES (?, ?, ?)",
            (project_id, "Linked Protocol", "test"),
        )
        conn.execute(
            """
            INSERT INTO raw_projects (
                raw_id, source_id, dedup_key, raw_data, discovered_at,
                processed, discovery_score, project_id
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                "raw-linked-1",
                "defillama",
                dedup,
                json.dumps(item.raw_data),
                datetime(2026, 7, 22, tzinfo=UTC).isoformat(),
                0.8,
                project_id,
            ),
        )
        conn.commit()

        snap_repo = EconomicSnapshotRepository(conn)
        evid_repo = OpportunityRepository(conn)
        writer = EconomicSnapshotWriter(snap_repo)
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        settings_obj = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=True,
        )

        result = _result([item], finished_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC))
        summary = process_persisted_collection(
            result,
            run_id="daily:2026-07-22:defillama",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
        assert summary is not None
        assert summary.snapshots_inserted >= 1
        assert len(summary.observations) >= 1
        evidence_rows = evid_repo.list_evidence(project_id)
        assert len(evidence_rows) >= 1

        # Unlinked path: different name/dedup → snapshot kept, zero Evidence for that project
        unlinked = _discovery(name="Unlinked Protocol", raw_id="raw-unlinked")
        summary2 = process_persisted_collection(
            _result([unlinked], finished_at=datetime(2026, 7, 22, 13, 0, tzinfo=UTC)),
            run_id="daily:2026-07-22:defillama",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
        assert summary2 is not None
        assert summary2.snapshots_inserted >= 1
        snap_count = raw.execute(
            "SELECT COUNT(*) FROM opportunity_economic_snapshots"
        ).fetchone()[0]
        assert snap_count >= 2
        # no project for unlinked identity
        unlinked_project = unlinked.project_id
        assert evid_repo.list_evidence(unlinked_project) == []
    finally:
        raw.close()


def test_evidence_off_real_writer_still_snapshots_skipped_flag_off() -> None:
    from app.metrics import OPPORTUNITY_ECONOMIC_EVIDENCE, metric_sample_value
    from app.opportunity.economic_evidence import EconomicEvidenceEmitter
    from app.opportunity.economic_integration import process_persisted_collection
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.economic_writer import EconomicSnapshotWriter
    from app.opportunity.repository import OpportunityRepository

    raw, conn = _sqlite_stack()
    try:
        snap_repo = EconomicSnapshotRepository(conn)
        evid_repo = OpportunityRepository(conn)
        writer = EconomicSnapshotWriter(snap_repo)
        emitter = EconomicEvidenceEmitter(conn, snap_repo, evid_repo)
        settings_obj = _settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_source_defillama_enabled=True,
            opportunity_economic_evidence_emit_enabled=False,
        )
        before = metric_sample_value(
            OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off"
        )
        summary = process_persisted_collection(
            _result([_discovery()]),
            run_id="daily:2026-07-22:defillama",
            writer=writer,
            emitter=emitter,
            settings_obj=settings_obj,
        )
        assert summary is not None
        assert summary.snapshots_inserted >= 1
        assert raw.execute(
            "SELECT COUNT(*) FROM opportunity_economic_snapshots"
        ).fetchone()[0] >= 1
        assert raw.execute("SELECT COUNT(*) FROM opportunity_evidence").fetchone()[0] == 0
        after = metric_sample_value(
            OPPORTUNITY_ECONOMIC_EVIDENCE, source="defillama", result="skipped_flag_off"
        )
        assert after >= before + 1
    finally:
        raw.close()
