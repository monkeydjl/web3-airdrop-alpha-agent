"""Tests for collection endpoints and auto-run flow."""

from __future__ import annotations

import contextlib
from datetime import UTC

import pytest
import respx
from fastapi.testclient import TestClient
from httpx import Response

from app.config import settings
from app.db import init_db
from app.inflight import (
    QUEUE_DRAIN_KEY,
    active_runs,
    claim_run,
    collect_key,
    reset_active_runs,
)
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    """创建测试客户端，每个测试使用独立数据库。"""
    db_path = tmp_path / "test.db"
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    return TestClient(app)


class TestCollectionsEndpoints:
    @respx.mock
    def test_trigger_defillama_collection(self, client: TestClient) -> None:
        """手动触发 DefiLlama 采集。"""
        protocols = [
            {
                "name": "Alpha Protocol",
                "slug": "alpha",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "Lending",
                "chains": ["Ethereum"],
                "url": "https://alpha.example.com",
                "twitter": "@alpha",
                "github": "alpha/repo",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

        response = client.post("/api/v1/collections/defillama/trigger")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["source_id"] == "defillama"
        assert data["items_collected"] == 1
        assert data["items_new"] == 1

    def test_list_collection_sources(self, client: TestClient) -> None:
        """列出采集源。"""
        response = client.get("/api/v1/collections/sources")

        assert response.status_code == 200
        sources = response.json()["data"]["sources"]
        assert any(s["source_id"] == "defillama" for s in sources)
        sample = next(s for s in sources if s["source_id"] == "defillama")
        assert "operator_enabled" in sample
        assert "config_ready" in sample
        assert "is_enabled" in sample

    def test_patch_collection_source_toggle(self, client: TestClient) -> None:
        """运营商开关写入 data_sources.enabled，并阻止 trigger。"""
        off = client.patch(
            "/api/v1/collections/defillama",
            json={"enabled": False},
        )
        assert off.status_code == 200
        body = off.json()["data"]
        assert body["operator_enabled"] is False
        assert body["status"]["enabled"] is False
        assert body["is_enabled"] is False

        blocked = client.post("/api/v1/collections/defillama/trigger")
        assert blocked.status_code == 400
        # main.py 把 HTTPException.detail 包进统一 {ok,error} 信封
        err = blocked.json().get("error") or blocked.json().get("detail") or {}
        assert err.get("code") == "SOURCE_DISABLED"

        on = client.patch(
            "/api/v1/collections/defillama",
            json={"enabled": True},
        )
        assert on.status_code == 200
        assert on.json()["data"]["operator_enabled"] is True
        assert on.json()["data"]["status"]["enabled"] is True

    def test_patch_unknown_source_404(self, client: TestClient) -> None:
        response = client.patch(
            "/api/v1/collections/not-a-real-source",
            json={"enabled": False},
        )
        assert response.status_code == 404

    def test_list_discoveries_empty(self, client: TestClient) -> None:
        """空发现列表。"""
        response = client.get("/api/v1/discoveries")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items"] == []
        assert data["total"] == 0


class TestRunAutoPath:
    @respx.mock
    def test_run_without_projects_uses_raw_projects(self, client: TestClient) -> None:
        """不提供 projects 时，自动从 raw_projects 表读取。"""
        # 先触发采集
        protocols = [
            {
                "name": "Auto Project",
                "slug": "auto-project",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "L2",
                "chains": ["Ethereum", "Arbitrum"],
                "url": "https://auto.example.com",
                "twitter": "@auto",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        trigger = client.post("/api/v1/collections/defillama/trigger")
        assert trigger.status_code == 200

        # 再运行 pipeline（不带 projects）
        response = client.post("/api/v1/run", json={})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_count"] >= 1
        assert data["status"] in ("completed", "partial")

    def test_run_without_projects_empty_db(self, client: TestClient) -> None:
        """数据库为空且不提供 projects 时返回空结果。"""
        response = client.post("/api/v1/run", json={})

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_count"] == 0

    @respx.mock
    def test_run_marks_raw_projects_processed(self, client: TestClient) -> None:
        """评分成功后 raw_projects 应标记 processed。"""
        protocols = [
            {
                "name": "MarkMe",
                "slug": "mark-me",
                "tvl": 5_000_000,
                "change_7d": 0.25,
                "category": "L2",
                "chains": ["Ethereum"],
                "url": "https://markme.example.com",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        assert client.post("/api/v1/collections/defillama/trigger").status_code == 200

        run = client.post("/api/v1/run", json={})
        assert run.status_code == 200
        assert run.json()["data"]["project_count"] >= 1

        discoveries = client.get("/api/v1/discoveries?processed=true")
        assert discoveries.status_code == 200
        items = discoveries.json()["data"]["items"]
        assert any(i.get("processed") for i in items) or discoveries.json()["data"]["total"] >= 1

    @respx.mock
    def test_trigger_with_auto_run(self, client: TestClient, monkeypatch) -> None:
        """COLLECTION_AUTO_RUN_ENABLED 时 trigger 后自动分析。"""
        monkeypatch.setattr(settings, "collection_auto_run_enabled", True)
        protocols = [
            {
                "name": "AutoRun",
                "slug": "auto-run",
                "tvl": 8_000_000,
                "change_7d": 0.3,
                "category": "DeFi",
                "chains": ["Ethereum", "Base"],
                "url": "https://autorun.example.com",
                "twitter": "@autorun",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))
        response = client.post("/api/v1/collections/defillama/trigger")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data.get("auto_run") is not None
        assert data["auto_run"]["project_count"] >= 1


class TestTriggerInFlightGuard:
    """重复触发防护（API-4）。守卫理由见 app/inflight.py。"""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        reset_active_runs()
        yield
        reset_active_runs()

    def test_reentrant_trigger_of_same_source_returns_409(self, client: TestClient) -> None:
        """同源采集在飞时重复 POST 返回 409，且不发第二次出站请求。"""
        with claim_run(collect_key("defillama")) as acquired:
            assert acquired
            response = client.post("/api/v1/collections/defillama/trigger")

        assert response.status_code == 409
        body = response.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "COLLECTION_IN_PROGRESS"

    def test_other_sources_are_not_blocked(self, client: TestClient) -> None:
        """守卫按 source_id 分键：一个源在飞不该挡住别的源。"""
        with claim_run(collect_key("defillama")) as acquired:
            assert acquired
            # github 采集器未配置 token 时 disabled → 400；关键是不能是 409
            response = client.post("/api/v1/collections/github/trigger")

        assert response.status_code != 409

    def test_guard_released_after_trigger_completes(self, client: TestClient) -> None:
        """一次触发结束后守卫必须释放，否则该源永久不可再采。"""
        with respx.mock:
            respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=[]))
            assert client.post("/api/v1/collections/defillama/trigger").status_code == 200

        assert collect_key("defillama") not in active_runs()

    @respx.mock
    def test_auto_run_skipped_when_drain_in_flight(self, client: TestClient, monkeypatch) -> None:
        """auto-run 撞上在飞排空时：采集仍成功，auto_run 标记为跳过而非报错。"""
        monkeypatch.setattr(settings, "collection_auto_run_enabled", True)
        protocols = [
            {
                "name": "SkipRun",
                "slug": "skip-run",
                "tvl": 8_000_000,
                "change_7d": 0.3,
                "category": "DeFi",
                "chains": ["Ethereum"],
                "url": "https://skiprun.example.com",
            }
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

        # 模拟另一处（cron / 另一个采集源的回调）正在排空队列
        with claim_run(QUEUE_DRAIN_KEY) as acquired:
            assert acquired
            response = client.post("/api/v1/collections/defillama/trigger")

        assert response.status_code == 200
        data = response.json()["data"]
        assert data["items_collected"] == 1
        assert data["auto_run"] is None
        assert data["auto_run_skipped"] == "queue_drain_in_progress"


# ── Task 7: manual trigger economic wiring ───────────────────────


def _collector_result(source_id: str = "defillama"):
    from datetime import datetime

    from app.collectors.base import CollectorResult, RawDiscovery

    item = RawDiscovery(
        source_id=source_id,
        raw_id=f"raw-{source_id}-manual",
        name=f"Manual {source_id}",
        url=f"https://example.com/{source_id}",
        sector="DeFi",
        stage="mainnet",
        raw_data={
            "tvl": 1_000_000,
            "change_7d": 0.05,
            "change_7d_unit": "ratio",
            "chains": ["Ethereum"],
        },
    )
    result = CollectorResult(source_id=source_id, items=[item], status="success")
    result.finished_at = datetime(2026, 7, 22, 16, 0, tzinfo=UTC)
    result.started_at = datetime(2026, 7, 22, 15, 0, tzinfo=UTC)
    return result


class _FakeCollector:
    def __init__(self, source_id: str = "defillama") -> None:
        self.source_id = source_id
        self.source_name = source_id
        self.source_type = "api"
        self.collect_calls = 0

    def is_enabled(self) -> bool:
        return True

    async def collect(self):
        self.collect_calls += 1
        return _collector_result(self.source_id)


class _FakeRegistry:
    def __init__(self, collectors: dict[str, _FakeCollector] | None = None) -> None:
        self._collectors = collectors or {"defillama": _FakeCollector("defillama")}

    def get(self, source_id: str):
        return self._collectors.get(source_id)

    def list_all(self):
        return list(self._collectors.values())


class TestManualTriggerEconomicIntegration:
    def test_request_scoped_conn_closed_once_and_manual_run_id(self, client: TestClient, monkeypatch) -> None:
        import app.routers.v1.collections as coll_mod

        close_calls = {"n": 0}
        seen_conns: list[object] = []

        class TrackingConn:
            def close(self) -> None:
                close_calls["n"] += 1

            def execute(self, *a, **k):
                from unittest.mock import MagicMock

                return MagicMock()

            def commit(self) -> None:
                return None

        conn = TrackingConn()

        class TrackingRepo:
            def __init__(self, c=None) -> None:
                seen_conns.append(("repo", c))
                self._conn = c

            def persist_collection_result(self, *a, **k) -> None:
                return None

            def _get_conn(self):
                return self._conn

            def _should_close(self) -> bool:
                return False

        process_calls: list[dict] = []

        def fake_process(result, *, run_id, writer, emitter, settings_obj):
            process_calls.append(
                {
                    "run_id": run_id,
                    "writer": writer,
                    "emitter": emitter,
                    "result": result,
                }
            )
            return None

        collector = _FakeCollector("defillama")
        monkeypatch.setattr(coll_mod, "_build_registry", lambda: _FakeRegistry({"defillama": collector}))
        monkeypatch.setattr(coll_mod, "CollectionRepository", TrackingRepo)
        monkeypatch.setattr(coll_mod, "get_connection", lambda: conn)
        monkeypatch.setattr(
            "app.opportunity.economic_repository.EconomicSnapshotRepository",
            lambda c=None, *a, **k: type("S", (), {"__init__": lambda self, *a, **k: None})(),
        )
        # Simpler: MagicMock factories that capture conn
        from unittest.mock import MagicMock

        snap_factory_conns: list = []
        emit_factory_conns: list = []

        def snap_factory(c=None, *a, **k):
            snap_factory_conns.append(c)
            return MagicMock()

        def opp_factory(c=None, *a, **k):
            return MagicMock()

        def writer_factory(*a, **k):
            return MagicMock()

        def emitter_factory(c, *a, **k):
            emit_factory_conns.append(c)
            return MagicMock()

        monkeypatch.setattr("app.opportunity.economic_repository.EconomicSnapshotRepository", snap_factory)
        monkeypatch.setattr("app.opportunity.repository.OpportunityRepository", opp_factory)
        monkeypatch.setattr("app.opportunity.economic_writer.EconomicSnapshotWriter", writer_factory)
        monkeypatch.setattr("app.opportunity.economic_evidence.EconomicEvidenceEmitter", emitter_factory)
        monkeypatch.setattr("app.opportunity.economic_integration.process_persisted_collection", fake_process)
        monkeypatch.setattr(
            "app.opportunity.economic_integration.manual_run_id",
            lambda **kw: "manual:550e8400-e29b-41d4-a716-446655440000",
        )
        monkeypatch.setattr(settings, "opportunity_economic_snapshot_enabled", True)
        monkeypatch.setattr(settings, "opportunity_economic_source_defillama_enabled", True)
        monkeypatch.setattr(settings, "defillama_enabled", True)
        monkeypatch.setattr(settings, "collection_auto_run_enabled", False)

        response = client.post("/api/v1/collections/defillama/trigger")
        assert response.status_code == 200
        assert collector.collect_calls == 1
        assert close_calls["n"] == 1
        assert any(c is conn for _, c in seen_conns)
        assert process_calls
        assert process_calls[0]["run_id"] == "manual:550e8400-e29b-41d4-a716-446655440000"
        assert snap_factory_conns and snap_factory_conns[0] is conn
        assert emit_factory_conns and emit_factory_conns[0] is conn

    def test_persist_failure_zero_economic_process(self, client: TestClient, monkeypatch) -> None:
        from unittest.mock import MagicMock

        import app.routers.v1.collections as coll_mod

        close_calls = {"n": 0}

        class TrackingConn:
            def close(self) -> None:
                close_calls["n"] += 1

        class FailingRepo:
            def __init__(self, c=None) -> None:
                pass

            def persist_collection_result(self, *a, **k) -> None:
                raise RuntimeError("persist failed")

            def _get_conn(self):
                # 与真实 CollectionRepository 接口对齐；无连接时返回 None。
                return None

            def _should_close(self) -> bool:
                return False

        process_mock = MagicMock()
        collector = _FakeCollector("defillama")
        monkeypatch.setattr(coll_mod, "_build_registry", lambda: _FakeRegistry({"defillama": collector}))
        monkeypatch.setattr(coll_mod, "CollectionRepository", FailingRepo)
        monkeypatch.setattr(coll_mod, "get_connection", lambda: TrackingConn())
        monkeypatch.setattr("app.opportunity.economic_integration.process_persisted_collection", process_mock)

        with contextlib.suppress(Exception):
            client.post("/api/v1/collections/defillama/trigger")

        process_mock.assert_not_called()
        assert close_calls["n"] == 1
        assert collector.collect_calls == 1

    def test_flags_all_false_baseline_response_and_zero_writer(self, client: TestClient, monkeypatch) -> None:
        from unittest.mock import MagicMock

        import app.routers.v1.collections as coll_mod

        for name in (
            "opportunity_economic_snapshot_enabled",
            "opportunity_economic_source_defillama_enabled",
            "opportunity_economic_source_coingecko_enabled",
            "opportunity_economic_source_cryptorank_enabled",
            "opportunity_economic_evidence_emit_enabled",
            "opportunity_economic_resolver_enabled",
        ):
            monkeypatch.setattr(settings, name, False)
        monkeypatch.setattr(settings, "collection_auto_run_enabled", False)

        close_calls = {"n": 0}

        class TrackingConn:
            def close(self) -> None:
                close_calls["n"] += 1

        class Repo:
            def __init__(self, c=None) -> None:
                pass

            def persist_collection_result(self, *a, **k) -> None:
                return None

            def _get_conn(self):
                # 与真实 CollectionRepository 接口对齐；无连接时返回 None。
                return None

            def _should_close(self) -> bool:
                return False

        writer_process = MagicMock()
        emitter_emit = MagicMock()

        def real_process(result, *, run_id, writer, emitter, settings_obj):
            # Use real integration if available; else assert flags off path
            from app.opportunity import economic_integration as ei

            return ei.process_persisted_collection(
                result,
                run_id=run_id,
                writer=writer,
                emitter=emitter,
                settings_obj=settings_obj,
            )

        collector = _FakeCollector("defillama")
        monkeypatch.setattr(coll_mod, "_build_registry", lambda: _FakeRegistry({"defillama": collector}))
        monkeypatch.setattr(coll_mod, "CollectionRepository", Repo)
        monkeypatch.setattr(coll_mod, "get_connection", lambda: TrackingConn())

        mock_writer = MagicMock()
        mock_writer.process = writer_process
        mock_emitter = MagicMock()
        mock_emitter.emit = emitter_emit
        monkeypatch.setattr(
            "app.opportunity.economic_repository.EconomicSnapshotRepository",
            lambda *a, **k: MagicMock(),
        )
        monkeypatch.setattr("app.opportunity.repository.OpportunityRepository", lambda *a, **k: MagicMock())
        monkeypatch.setattr(
            "app.opportunity.economic_writer.EconomicSnapshotWriter",
            lambda *a, **k: mock_writer,
        )
        monkeypatch.setattr(
            "app.opportunity.economic_evidence.EconomicEvidenceEmitter",
            lambda *a, **k: mock_emitter,
        )

        # Prefer real process_persisted_collection once module exists
        try:
            import app.opportunity.economic_integration  # noqa: F401

            monkeypatch.setattr(
                "app.opportunity.economic_integration.process_persisted_collection",
                real_process,
            )
        except ImportError:
            pass

        response = client.post("/api/v1/collections/defillama/trigger")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        assert body["data"]["source_id"] == "defillama"
        assert body["data"]["status"] == "success"
        assert body["data"]["items_collected"] == 1
        assert "auto_run" in body["data"]
        assert collector.collect_calls == 1
        assert close_calls["n"] == 1
        # gate off → no writer/emitter
        writer_process.assert_not_called()
        emitter_emit.assert_not_called()

    @pytest.mark.parametrize("source_id", ["defillama", "coingecko", "cryptorank"])
    @pytest.mark.parametrize("fail_stage", ["construction", "process", "emit"])
    def test_manual_failure_isolation_response_byte_identical(
        self, client: TestClient, monkeypatch, source_id: str, fail_stage: str
    ) -> None:
        """Construction/process/emit failures keep CollectionTriggerResponse.model_dump identical.

        process/emit stages run real process_persisted_collection with injected writer/emitter
        failures (not whole-boundary mocks of the integration function).
        """
        from datetime import datetime, timedelta
        from types import SimpleNamespace
        from unittest.mock import MagicMock

        import app.routers.v1.collections as coll_mod
        from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation
        from app.opportunity.economic_writer import EconomicWriteSummary
        from app.routers.v1.collections import CollectionTriggerResponse

        monkeypatch.setattr(settings, "opportunity_economic_snapshot_enabled", True)
        monkeypatch.setattr(settings, "opportunity_economic_source_defillama_enabled", False)
        monkeypatch.setattr(settings, "opportunity_economic_source_coingecko_enabled", False)
        monkeypatch.setattr(settings, "opportunity_economic_source_cryptorank_enabled", False)
        monkeypatch.setattr(settings, f"opportunity_economic_source_{source_id}_enabled", True)
        monkeypatch.setattr(settings, f"{source_id}_enabled", True)
        monkeypatch.setattr(settings, "opportunity_economic_evidence_emit_enabled", True)
        monkeypatch.setattr(settings, "collection_auto_run_enabled", True)

        close_calls = {"n": 0}
        analysis_calls = {"n": 0}
        mock_writer: MagicMock | None = None
        mock_emitter: MagicMock | None = None

        class TrackingConn:
            def close(self) -> None:
                close_calls["n"] += 1

        class Repo:
            def __init__(self, c=None) -> None:
                pass

            def persist_collection_result(self, *a, **k) -> None:
                return None

            def _get_conn(self):
                # 与真实 CollectionRepository 接口对齐；无连接时返回 None。
                return None

            def _should_close(self) -> bool:
                return False

        async def fake_pipeline(**kwargs):
            analysis_calls["n"] += 1
            return {"project_count": 0, "status": "completed"}

        collector = _FakeCollector(source_id)
        expected_result = _collector_result(source_id)
        baseline = CollectionTriggerResponse(
            ok=True,
            data={
                "source_id": source_id,
                "status": expected_result.status,
                "items_collected": len(expected_result.items),
                "items_new": expected_result.items_new,
                "items_duplicate": expected_result.items_duplicate,
                "started_at": (expected_result.started_at.isoformat() if expected_result.started_at else None),
                "finished_at": (expected_result.finished_at.isoformat() if expected_result.finished_at else None),
                "auto_run": {"project_count": 0, "status": "completed"},
                "auto_run_skipped": None,
            },
        ).model_dump()

        registry = _FakeRegistry({source_id: collector})
        monkeypatch.setattr(coll_mod, "_build_registry", lambda: registry)
        monkeypatch.setattr(coll_mod, "CollectionRepository", Repo)
        monkeypatch.setattr(coll_mod, "get_connection", lambda: TrackingConn())
        monkeypatch.setattr("app.pipeline_run.execute_analysis_pipeline", fake_pipeline)

        if fail_stage == "construction":

            def boom(*a, **k):
                raise RuntimeError("construction boom")

            monkeypatch.setattr("app.opportunity.economic_repository.EconomicSnapshotRepository", boom)
        else:
            mock_writer = MagicMock(name="writer")
            mock_emitter = MagicMock(name="emitter")
            if fail_stage == "process":
                mock_writer.process.side_effect = RuntimeError("process boom")
            else:
                now = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)

                def _obs(snapshot_id: str) -> NormalizedObservation:
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

                o1, o2 = _obs("snap-a"), _obs("snap-b")
                mock_writer.process.return_value = EconomicWriteSummary(
                    source_id=source_id,
                    run_id=f"manual:test-{source_id}",
                    observations=(o1, o2),
                    snapshots_inserted=2,
                    snapshots_duplicate=0,
                    schema_invalid=0,
                    skipped_flag_off=0,
                )
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

        response = client.post(f"/api/v1/collections/{source_id}/trigger")
        assert response.status_code == 200
        dump = response.json()
        # True baseline model_dump equality (not merely shape/key checks)
        assert CollectionTriggerResponse.model_validate(dump).model_dump() == baseline
        assert dump == baseline
        # analysis not suppressed
        assert analysis_calls["n"] == 1
        assert close_calls["n"] == 1
        assert collector.collect_calls == 1

        if fail_stage == "process":
            assert mock_writer is not None and mock_emitter is not None
            mock_writer.process.assert_called_once()
            mock_emitter.emit.assert_not_called()
        elif fail_stage == "emit":
            assert mock_writer is not None and mock_emitter is not None
            mock_writer.process.assert_called_once()
            assert mock_emitter.emit.call_count == 2
