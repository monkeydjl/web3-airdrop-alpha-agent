"""Focused tests for application lifespan resource management + Task 7 economic wiring."""

from __future__ import annotations

import contextlib
import sqlite3
import warnings
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.collectors.base import CollectorResult, RawDiscovery
from app.db import DbConnection, init_db


class _FakeRegistry:
    def __init__(self) -> None:
        self.collectors: list[object] = []

    def register(self, collector: object) -> None:
        self.collectors.append(collector)


class _FakeCollectionScheduler:
    instances: ClassVar[list[_FakeCollectionScheduler]] = []

    def __init__(self, registry: object, on_collection: object) -> None:
        self.registry = registry
        self.on_collection = on_collection
        self.start_calls = 0
        self.shutdown_calls: list[bool] = []
        self.raise_on_shutdown = False
        self.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1

    def shutdown(self, *, wait: bool) -> None:
        self.shutdown_calls.append(wait)
        if self.raise_on_shutdown:
            raise RuntimeError("collection shutdown failed")


class _FakeAnalysisScheduler:
    instances: ClassVar[list[_FakeAnalysisScheduler]] = []

    def __init__(self) -> None:
        self.start_calls = 0
        self.shutdown_calls: list[bool] = []
        self.instances.append(self)

    def start(self) -> None:
        self.start_calls += 1

    def shutdown(self, *, wait: bool) -> None:
        self.shutdown_calls.append(wait)


class _TrackingConn:
    """Connection stand-in that records close calls."""

    def __init__(self, inner: Any | None = None) -> None:
        self.close_calls = 0
        self.inner = inner
        self.usable = True

    def close(self) -> None:
        self.close_calls += 1
        self.usable = False
        if self.inner is not None and hasattr(self.inner, "close"):
            self.inner.close()

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        if not self.usable:
            raise RuntimeError("connection closed")
        if self.inner is not None:
            return self.inner.execute(*args, **kwargs)
        return MagicMock()

    def commit(self) -> None:
        if self.inner is not None:
            self.inner.commit()


def _patch_non_testing_dependencies(monkeypatch) -> None:
    _FakeCollectionScheduler.instances.clear()
    _FakeAnalysisScheduler.instances.clear()
    monkeypatch.setattr(main_module.settings, "app_env", "development")
    monkeypatch.setattr(main_module.settings, "collection_auto_run_enabled", False)
    monkeypatch.setattr(main_module, "CollectorRegistry", _FakeRegistry)
    monkeypatch.setattr(main_module, "CollectionScheduler", _FakeCollectionScheduler)
    monkeypatch.setattr(main_module, "AnalysisScheduler", _FakeAnalysisScheduler)
    monkeypatch.setattr(main_module, "CollectionRepository", lambda *a, **k: object())
    for collector_name in (
        "DefiLlamaCollector",
        "GitHubCollector",
        "CoinGeckoCollector",
        "CryptoRankCollector",
        "RootDataCollector",
        "TwitterKolCollector",
        "TwitterKeywordCollector",
        "EtherscanCollector",
        "GalxeCollector",
        "Layer3Collector",
    ):
        monkeypatch.setattr(main_module, collector_name, lambda: object())


def _disable_economic_flags(monkeypatch) -> None:
    for name in (
        "opportunity_economic_snapshot_enabled",
        "opportunity_economic_source_defillama_enabled",
        "opportunity_economic_source_coingecko_enabled",
        "opportunity_economic_source_cryptorank_enabled",
        "opportunity_economic_evidence_emit_enabled",
        "opportunity_economic_resolver_enabled",
    ):
        monkeypatch.setattr(main_module.settings, name, False)


def _enable_source_flags(monkeypatch, source_id: str, *, evidence: bool = False) -> None:
    monkeypatch.setattr(main_module.settings, "opportunity_economic_snapshot_enabled", True)
    monkeypatch.setattr(main_module.settings, "opportunity_economic_evidence_emit_enabled", evidence)
    monkeypatch.setattr(main_module.settings, "opportunity_economic_source_defillama_enabled", False)
    monkeypatch.setattr(main_module.settings, "opportunity_economic_source_coingecko_enabled", False)
    monkeypatch.setattr(main_module.settings, "opportunity_economic_source_cryptorank_enabled", False)
    flag = {
        "defillama": "opportunity_economic_source_defillama_enabled",
        "coingecko": "opportunity_economic_source_coingecko_enabled",
        "cryptorank": "opportunity_economic_source_cryptorank_enabled",
    }[source_id]
    monkeypatch.setattr(main_module.settings, flag, True)
    monkeypatch.setattr(main_module.settings, f"{source_id}_enabled", True)


def _make_result(source_id: str = "defillama") -> CollectorResult:
    item = RawDiscovery(
        source_id=source_id,
        raw_id=f"raw-{source_id}-1",
        name=f"{source_id.title()} Protocol",
        url=f"https://example.com/{source_id}",
        sector="DeFi",
        stage="mainnet",
        raw_data={"tvl": 1_000_000, "change_7d": 0.05, "change_7d_unit": "ratio", "chains": ["Ethereum"]},
    )
    result = CollectorResult(source_id=source_id, items=[item], status="success")
    result.finished_at = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    result.started_at = datetime(2026, 7, 22, 14, 0, tzinfo=UTC)
    return result


def test_testing_lifespan_sets_scheduler_states_to_none(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "app_env", "testing")
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    application = main_module.create_app()

    with TestClient(application):
        assert application.state.collector_registry is None
        assert application.state.collection_scheduler is None
        assert application.state.analysis_scheduler is None


def test_non_testing_lifespan_starts_and_stops_each_scheduler_once(monkeypatch) -> None:
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    # Stub economic constructors so lifespan can build shared stack
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )
    application = main_module.create_app()

    with TestClient(application):
        collection_scheduler = _FakeCollectionScheduler.instances[0]
        analysis_scheduler = _FakeAnalysisScheduler.instances[0]
        assert collection_scheduler.start_calls == 1
        assert analysis_scheduler.start_calls == 1
        assert len(application.state.collector_registry.collectors) == 10
        assert application.state.collection_scheduler is collection_scheduler
        assert application.state.analysis_scheduler is analysis_scheduler

    assert collection_scheduler.shutdown_calls == [True]
    assert analysis_scheduler.shutdown_calls == [True]
    assert owned.close_calls == 1


def test_shutdown_failure_does_not_prevent_second_scheduler_shutdown(monkeypatch) -> None:
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )
    application = main_module.create_app()

    with TestClient(application):
        collection_scheduler = _FakeCollectionScheduler.instances[0]
        analysis_scheduler = _FakeAnalysisScheduler.instances[0]
        collection_scheduler.raise_on_shutdown = True

    assert collection_scheduler.shutdown_calls == [True]
    assert analysis_scheduler.shutdown_calls == [True]
    assert owned.close_calls == 1


def test_db_override_suppresses_lifespan_database_initialization(monkeypatch) -> None:
    init_calls: list[None] = []
    monkeypatch.setattr(main_module.settings, "app_env", "testing")
    monkeypatch.setattr(main_module, "init_db", lambda: init_calls.append(None))

    application = main_module.create_app(db_override=object())
    with TestClient(application):
        pass

    assert init_calls == []


def test_create_app_does_not_register_deprecated_on_event_hooks(monkeypatch) -> None:
    monkeypatch.setattr(main_module.settings, "app_env", "testing")
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        main_module.create_app(db_override=object())

    assert not [warning for warning in caught if "on_event is deprecated" in str(warning.message)]


def test_db_override_borrowed_never_closed_and_remains_usable(monkeypatch) -> None:
    """Injected db_override is borrowed; lifespan never closes it."""
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    borrowed = _TrackingConn(conn)

    get_conn = MagicMock(side_effect=AssertionError("must not call get_connection when override set"))
    monkeypatch.setattr(main_module, "get_connection", get_conn)

    repo_conns: list[Any] = []

    class TrackingCollectionRepository:
        def __init__(self, c=None) -> None:
            repo_conns.append(c)

        def persist_collection_result(self, *a, **k) -> None:
            return None

    monkeypatch.setattr(main_module, "CollectionRepository", TrackingCollectionRepository)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda c=None, *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda c=None, *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )

    application = main_module.create_app(db_override=borrowed)
    with TestClient(application):
        assert repo_conns and repo_conns[0] is borrowed

    assert borrowed.close_calls == 0
    assert borrowed.usable is True
    # still usable after lifespan exit
    assert borrowed.execute("SELECT 1").fetchone()[0] == 1
    raw.close()


def test_app_owned_connection_closes_exactly_once_on_shutdown(monkeypatch) -> None:
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )

    application = main_module.create_app()
    with TestClient(application):
        assert owned.close_calls == 0
    assert owned.close_calls == 1


def test_app_owned_connection_closes_once_on_startup_failure_after_get_connection(
    monkeypatch,
) -> None:
    """App-owned conn closes exactly once when lifespan startup fails after acquire."""
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )

    class BoomCollectionScheduler(_FakeCollectionScheduler):
        def start(self) -> None:
            raise RuntimeError("collector/scheduler startup boom")

    monkeypatch.setattr(main_module, "CollectionScheduler", BoomCollectionScheduler)

    application = main_module.create_app()
    with pytest.raises(RuntimeError, match="startup boom"), TestClient(application):
        pass

    assert owned.close_calls == 1


def test_borrowed_override_never_closed_on_startup_failure(monkeypatch) -> None:
    """Borrowed db_override is never closed when lifespan startup fails post-acquire."""
    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)

    raw = sqlite3.connect(":memory:")
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)
    borrowed = _TrackingConn(conn)

    get_conn = MagicMock(
        side_effect=AssertionError("must not call get_connection when override set")
    )
    monkeypatch.setattr(main_module, "get_connection", get_conn)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )

    class BoomCollectionScheduler(_FakeCollectionScheduler):
        def start(self) -> None:
            raise RuntimeError("borrowed-path startup boom")

    monkeypatch.setattr(main_module, "CollectionScheduler", BoomCollectionScheduler)

    application = main_module.create_app(db_override=borrowed)
    with pytest.raises(RuntimeError, match="borrowed-path startup boom"), TestClient(application):
        pass

    assert borrowed.close_calls == 0
    assert borrowed.usable is True
    assert borrowed.execute("SELECT 1").fetchone()[0] == 1
    raw.close()


def test_on_collection_persist_then_process_with_daily_run_id_then_analysis(
    monkeypatch,
) -> None:
    _patch_non_testing_dependencies(monkeypatch)
    _enable_source_flags(monkeypatch, "defillama", evidence=True)
    monkeypatch.setattr(main_module.settings, "collection_auto_run_enabled", True)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)

    order: list[str] = []
    persist_calls: list[Any] = []

    class TrackingRepo:
        def __init__(self, c=None) -> None:
            self.conn = c

        def persist_collection_result(self, result, **kwargs) -> None:
            order.append("persist")
            persist_calls.append((result, kwargs))

    process_calls: list[dict[str, Any]] = []

    def fake_process(result, *, run_id, writer, emitter, settings_obj):
        order.append("economic")
        process_calls.append(
            {
                "result": result,
                "run_id": run_id,
                "writer": writer,
                "emitter": emitter,
                "settings_obj": settings_obj,
            }
        )
        return None

    async def fake_pipeline(**kwargs):
        order.append("analysis")
        return {"project_count": 0}

    writer_obj = MagicMock(name="writer")
    emitter_obj = MagicMock(name="emitter")
    monkeypatch.setattr(main_module, "CollectionRepository", TrackingRepo)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: writer_obj,
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: emitter_obj,
    )
    monkeypatch.setattr(
        "app.opportunity.economic_integration.process_persisted_collection",
        fake_process,
    )
    monkeypatch.setattr(main_module, "execute_analysis_pipeline", fake_pipeline)

    application = main_module.create_app()
    with TestClient(application):
        on_collection = _FakeCollectionScheduler.instances[0].on_collection
        result = _make_result("defillama")
        import asyncio

        asyncio.run(on_collection("defillama", result))

    assert order == ["persist", "economic", "analysis"]
    assert len(persist_calls) == 1
    assert len(process_calls) == 1
    assert process_calls[0]["run_id"] == "daily:2026-07-22:defillama"
    assert process_calls[0]["writer"] is writer_obj
    assert process_calls[0]["emitter"] is emitter_obj
    assert process_calls[0]["result"] is result


def test_on_collection_persist_failure_zero_writer_emitter(monkeypatch) -> None:
    import asyncio

    _patch_non_testing_dependencies(monkeypatch)
    _enable_source_flags(monkeypatch, "defillama")
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)

    class FailingRepo:
        def __init__(self, c=None) -> None:
            pass

        def persist_collection_result(self, *a, **k) -> None:
            raise RuntimeError("persist failed")

    process_mock = MagicMock()
    monkeypatch.setattr(main_module, "CollectionRepository", FailingRepo)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_integration.process_persisted_collection",
        process_mock,
    )

    application = main_module.create_app()
    with TestClient(application):
        on_collection = _FakeCollectionScheduler.instances[0].on_collection
        with contextlib.suppress(RuntimeError):
            asyncio.run(on_collection("defillama", _make_result()))

    process_mock.assert_not_called()


def test_flags_all_false_on_collection_zero_economic_calls(monkeypatch) -> None:
    import asyncio

    _patch_non_testing_dependencies(monkeypatch)
    _disable_economic_flags(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)

    class Repo:
        def __init__(self, c=None) -> None:
            pass

        def persist_collection_result(self, *a, **k) -> None:
            return None

    process_mock = MagicMock()
    monkeypatch.setattr(main_module, "CollectionRepository", Repo)
    monkeypatch.setattr(
        "app.opportunity.economic_repository.EconomicSnapshotRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.repository.OpportunityRepository",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_writer.EconomicSnapshotWriter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
        lambda *a, **k: MagicMock(),
    )
    monkeypatch.setattr(
        "app.opportunity.economic_integration.process_persisted_collection",
        process_mock,
    )

    application = main_module.create_app()
    with TestClient(application):
        on_collection = _FakeCollectionScheduler.instances[0].on_collection
        asyncio.run(on_collection("defillama", _make_result()))

    # process is called once after persist (gate lives inside process → zero writer/emitter)
    process_mock.assert_called_once()

def _make_observation(snapshot_id: str, source_id: str = "defillama") -> Any:
    from datetime import timedelta

    from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation

    now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
    return NormalizedObservation(
        snapshot_id=snapshot_id,
        source_id=source_id,
        dedup_key=f"protocol:{snapshot_id}",
        provider_entity_id=f"entity-{snapshot_id}",
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


def _make_write_summary(source_id: str, observations: tuple[Any, ...]) -> Any:
    from app.opportunity.economic_writer import EconomicWriteSummary

    return EconomicWriteSummary(
        source_id=source_id,
        run_id=f"daily:2026-07-22:{source_id}",
        observations=observations,
        snapshots_inserted=len(observations),
        snapshots_duplicate=0,
        schema_invalid=0,
        skipped_flag_off=0,
    )


@pytest.mark.parametrize("source_id", ["defillama", "coingecko", "cryptorank"])
@pytest.mark.parametrize("fail_stage", ["construction", "process", "emit"])
def test_scheduled_failure_isolation_per_provider(
    monkeypatch, source_id: str, fail_stage: str
) -> None:
    """Construction/process/emit failures cannot rollback persist, suppress analysis, or leak conn.

    process/emit stages run real process_persisted_collection with injected writer/emitter
    failures (not whole-boundary mocks of the integration function).
    """
    import asyncio
    from types import SimpleNamespace

    _patch_non_testing_dependencies(monkeypatch)
    _enable_source_flags(monkeypatch, source_id, evidence=True)
    monkeypatch.setattr(main_module.settings, "collection_auto_run_enabled", True)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    owned = _TrackingConn()
    monkeypatch.setattr(main_module, "get_connection", lambda: owned)

    persist_count = {"n": 0}
    analysis_count = {"n": 0}
    mock_writer: MagicMock | None = None
    mock_emitter: MagicMock | None = None

    class Repo:
        def __init__(self, c=None) -> None:
            self.conn = c

        def persist_collection_result(self, *a, **k) -> None:
            persist_count["n"] += 1

    async def fake_pipeline(**kwargs):
        analysis_count["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(main_module, "CollectionRepository", Repo)
    monkeypatch.setattr(main_module, "execute_analysis_pipeline", fake_pipeline)

    if fail_stage == "construction":
        # Shared-stack construction fails at lifespan; must not prevent scheduler start.
        def boom_snap(*a, **k):
            raise RuntimeError("construction boom")

        monkeypatch.setattr(
            "app.opportunity.economic_repository.EconomicSnapshotRepository",
            boom_snap,
        )
        monkeypatch.setattr(
            "app.opportunity.repository.OpportunityRepository",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "app.opportunity.economic_writer.EconomicSnapshotWriter",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
            lambda *a, **k: MagicMock(),
        )
    else:
        mock_writer = MagicMock(name="writer")
        mock_emitter = MagicMock(name="emitter")
        if fail_stage == "process":
            mock_writer.process.side_effect = RuntimeError("process boom")
        else:
            o1 = _make_observation("snap-a", source_id)
            o2 = _make_observation("snap-b", source_id)
            mock_writer.process.return_value = _make_write_summary(source_id, (o1, o2))
            mock_emitter.emit.side_effect = [
                RuntimeError("emit boom"),
                SimpleNamespace(emitted=1, skipped_flag_off=0),
            ]

        monkeypatch.setattr(
            "app.opportunity.economic_repository.EconomicSnapshotRepository",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "app.opportunity.repository.OpportunityRepository",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr(
            "app.opportunity.economic_writer.EconomicSnapshotWriter",
            lambda *a, **k: mock_writer,
        )
        monkeypatch.setattr(
            "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
            lambda *a, **k: mock_emitter,
        )
        # Real process_persisted_collection — do not mock the whole boundary.

    application = main_module.create_app()
    with TestClient(application):
        assert _FakeCollectionScheduler.instances, "scheduler must start despite economic failures"
        on_collection = _FakeCollectionScheduler.instances[0].on_collection
        asyncio.run(on_collection(source_id, _make_result(source_id)))
        # other source unaffected
        asyncio.run(on_collection("github", _make_result("github")))

    assert persist_count["n"] == 2
    assert analysis_count["n"] == 2
    assert owned.close_calls == 1

    if fail_stage == "process":
        assert mock_writer is not None and mock_emitter is not None
        mock_writer.process.assert_called_once()
        mock_emitter.emit.assert_not_called()
    elif fail_stage == "emit":
        assert mock_writer is not None and mock_emitter is not None
        mock_writer.process.assert_called_once()
        # First emit fails; second observation still attempted on the same emitter.
        assert mock_emitter.emit.call_count == 2
        # github (unsupported) must not invoke writer again
        assert mock_writer.process.call_count == 1
