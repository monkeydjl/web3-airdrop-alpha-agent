"""Focused tests for application lifespan resource management."""

from __future__ import annotations

import warnings
from typing import ClassVar

from fastapi.testclient import TestClient

import app.main as main_module


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


def _patch_non_testing_dependencies(monkeypatch) -> None:
    _FakeCollectionScheduler.instances.clear()
    _FakeAnalysisScheduler.instances.clear()
    monkeypatch.setattr(main_module.settings, "app_env", "development")
    monkeypatch.setattr(main_module.settings, "collection_auto_run_enabled", False)
    # 采集器注册表现由 app.collectors.factory 统一构建并进程内共享
    monkeypatch.setattr(main_module, "get_default_registry", _FakeRegistry)
    monkeypatch.setattr(main_module, "CollectionScheduler", _FakeCollectionScheduler)
    monkeypatch.setattr(main_module, "AnalysisScheduler", _FakeAnalysisScheduler)
    monkeypatch.setattr(main_module, "CollectionRepository", lambda: object())


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
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    application = main_module.create_app()

    with TestClient(application):
        collection_scheduler = _FakeCollectionScheduler.instances[0]
        analysis_scheduler = _FakeAnalysisScheduler.instances[0]
        assert collection_scheduler.start_calls == 1
        assert analysis_scheduler.start_calls == 1
        assert application.state.collector_registry is not None
        assert application.state.collection_scheduler is collection_scheduler
        assert application.state.analysis_scheduler is analysis_scheduler

    assert collection_scheduler.shutdown_calls == [True]
    assert analysis_scheduler.shutdown_calls == [True]


def test_default_registry_covers_all_collectors_and_is_shared() -> None:
    """采集器注册表须覆盖全部 10 个源，且调度器与 API 路由共用同一实例。

    共用是限流正确性的前提：令牌桶是实例状态，每请求新建等于每次满桶。
    """
    from app.collectors.factory import build_default_registry, get_default_registry
    from app.routers.v1 import collections as collections_router

    assert len(build_default_registry()) == 10
    shared = get_default_registry()
    assert len(shared) == 10
    assert collections_router._build_registry() is shared
    # 同一 source 多次取用必须是同一对象（否则限流器被重置）
    assert shared.get("defillama") is get_default_registry().get("defillama")


def test_shutdown_failure_does_not_prevent_second_scheduler_shutdown(monkeypatch) -> None:
    _patch_non_testing_dependencies(monkeypatch)
    monkeypatch.setattr(main_module, "init_db", lambda: None)
    application = main_module.create_app()

    with TestClient(application):
        collection_scheduler = _FakeCollectionScheduler.instances[0]
        analysis_scheduler = _FakeAnalysisScheduler.instances[0]
        collection_scheduler.raise_on_shutdown = True

    assert collection_scheduler.shutdown_calls == [True]
    assert analysis_scheduler.shutdown_calls == [True]


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
