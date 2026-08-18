"""Tests for handoff: selective mark processed + analysis pipeline helper."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, call, patch

import pytest
from pydantic import ValidationError

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.collectors.persistence import CollectionRepository
from app.config import Settings
from app.db import init_db
from app.inflight import (
    QUEUE_DRAIN_KEY,
    QueueDrainInProgressError,
    active_runs,
    reset_active_runs,
)
from app.pipeline_run import (
    execute_analysis_pipeline,
    is_opportunity_shadow_sampled,
    mark_successful_raw_projects,
    opportunity_shadow_bucket,
    run_opportunity_shadow,
)
from app.repository import ProjectRepository
from app.utils.normalize import create_dedup_key, generate_deterministic_id


@pytest.fixture
def repo_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _insert_raw(conn, raw_id: str, name: str, score: float = 0.6) -> str:
    dedup = create_dedup_key(name, "L2").to_string()
    project_id = generate_deterministic_id(create_dedup_key(name, "L2"))
    raw_data = json.dumps({"name": name, "sector": "L2", "url": f"https://{name}.xyz"})
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (raw_id, "defillama", dedup, raw_data, datetime.now(UTC).isoformat(), score, project_id),
    )
    conn.commit()
    return project_id


def test_opportunity_shadow_defaults_enabled_and_full_sampling(monkeypatch):
    monkeypatch.delenv("OPPORTUNITY_SHADOW_ENABLED", raising=False)
    monkeypatch.delenv("OPPORTUNITY_SHADOW_SAMPLE_RATE", raising=False)

    configured = Settings(_env_file=None)

    assert configured.opportunity_shadow_enabled is True
    assert configured.opportunity_shadow_sample_rate == 1.0


@pytest.mark.parametrize("sample_rate", [0.0, 0.05, 1.0])
def test_opportunity_shadow_sample_rate_accepts_closed_interval(sample_rate):
    assert (
        Settings(_env_file=None, opportunity_shadow_sample_rate=sample_rate).opportunity_shadow_sample_rate
        == sample_rate
    )


@pytest.mark.parametrize("sample_rate", [-0.01, 1.01, float("inf"), float("-inf"), float("nan")])
def test_opportunity_shadow_sample_rate_rejects_invalid_values(sample_rate):
    with pytest.raises(ValidationError, match="sample rate must be finite and between 0 and 1"):
        Settings(_env_file=None, opportunity_shadow_sample_rate=sample_rate)


@pytest.mark.parametrize(
    ("project_id", "expected_bucket"),
    [
        ("project-1", 3389),
        ("alpha", 2974),
    ],
)
def test_opportunity_shadow_bucket_is_stable(project_id, expected_bucket):
    assert opportunity_shadow_bucket(project_id) == expected_bucket


@pytest.mark.parametrize("project_id", [None, "", "   "])
def test_opportunity_shadow_sampling_rejects_empty_ids(project_id):
    assert is_opportunity_shadow_sampled(project_id, 1.0) is False


def test_opportunity_shadow_sampling_has_explicit_boundaries():
    assert is_opportunity_shadow_sampled("project-1", 0.0) is False
    assert is_opportunity_shadow_sampled("project-1", 1.0) is True


def test_opportunity_shadow_sampling_is_monotonic():
    project_ids = [f"project-{index}" for index in range(500)]
    low = {project_id for project_id in project_ids if is_opportunity_shadow_sampled(project_id, 0.05)}
    high = {project_id for project_id in project_ids if is_opportunity_shadow_sampled(project_id, 0.25)}

    assert low
    assert low < high


EMPTY_SHADOW_STATS = {
    "eligible": 0,
    "sampled": 0,
    "attempted": 0,
    "saved": 0,
    "failed": 0,
    "skipped": 0,
}


class TestRunOpportunityShadow:
    def test_disabled_does_not_construct_service(self):
        service_factory = Mock()

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=False,
            sample_rate=0.0,
            service_factory=service_factory,
        )

        assert stats == EMPTY_SHADOW_STATS
        service_factory.assert_not_called()

    def test_skips_unscored_states_without_mutating_and_closes_once(self):
        rows = [{"id": "scored", "score": 80}, {"id": "unscored", "score": None}]
        before = deepcopy(rows)
        service = MagicMock()
        service.__enter__.return_value = service

        stats = run_opportunity_shadow(
            rows,
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "sampled": 1, "attempted": 1, "saved": 1}
        service.evaluate_row.assert_called_once_with(rows[0])
        service.__enter__.assert_called_once_with()
        service.__exit__.assert_called_once()
        assert rows == before

    def test_continues_after_each_state_failure(self):
        rows = [{"id": "bad", "score": 40}, {"id": "good", "score": 70}]
        service = MagicMock()
        service.__enter__.return_value = service
        service.evaluate_row.side_effect = [RuntimeError("shadow failed"), object()]

        stats = run_opportunity_shadow(
            rows,
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert stats == {**EMPTY_SHADOW_STATS, "eligible": 2, "sampled": 2, "attempted": 2, "saved": 1, "failed": 1}
        assert service.evaluate_row.call_args_list == [call(rows[0]), call(rows[1])]

    @pytest.mark.parametrize("failure_point", ["constructor", "enter"])
    def test_lifecycle_start_failure_has_truthful_zero_stats(self, failure_point):
        service_factory = Mock(side_effect=RuntimeError("constructor failed"))
        if failure_point == "enter":
            service = MagicMock()
            service.__enter__.side_effect = RuntimeError("enter failed")
            service_factory = Mock(return_value=service)

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=service_factory,
        )

        assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "sampled": 1}

    @pytest.mark.parametrize("failure_point", ["constructor", "enter"])
    def test_lifecycle_start_failure_records_summary_and_duration(self, monkeypatch, failure_point):
        service_factory = Mock(side_effect=RuntimeError("constructor failed"))
        if failure_point == "enter":
            service = MagicMock()
            service.__enter__.side_effect = RuntimeError("enter failed")
            service_factory = Mock(return_value=service)
        summary = Mock()
        duration = Mock()
        monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_projects", summary)
        monkeypatch.setattr("app.pipeline_run.observe_opportunity_shadow_duration", duration)

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=service_factory,
        )

        summary.assert_called_once_with(stats)
        duration.assert_called_once()

    def test_evaluation_failure_does_not_record_assessment_metric(self, monkeypatch):
        service = MagicMock()
        service.__enter__.return_value = service
        service.evaluate_row.side_effect = RuntimeError("evaluation failed")
        assessment_metric = Mock()
        monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_assessment", assessment_metric)

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert stats["failed"] == 1
        assessment_metric.assert_not_called()

    def test_exit_failure_does_not_relabel_saved_assessments(self):
        service = MagicMock()
        service.__enter__.return_value = service
        service.__exit__.side_effect = RuntimeError("close failed")

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "sampled": 1, "attempted": 1, "saved": 1}

    def test_empty_persisted_rows_do_not_construct_service(self):
        service_factory = Mock()

        stats = run_opportunity_shadow(
            [],
            enabled=True,
            sample_rate=1.0,
            service_factory=service_factory,
        )

        assert stats == EMPTY_SHADOW_STATS
        service_factory.assert_not_called()

    def test_records_saved_assessment_and_batch_summary(self, monkeypatch):
        assessment = SimpleNamespace(
            status="MONITOR",
            public_label="WATCH",
            model_version="opportunity-v2.0",
            profile_version="low-cost-curated-multiwallet-v1",
        )
        service = MagicMock()
        service.__enter__.return_value = service
        service.evaluate_row.return_value = assessment
        recorded = []
        monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_assessment", recorded.append)
        monkeypatch.setattr(
            "app.pipeline_run.record_opportunity_shadow_projects",
            lambda stats: recorded.append(stats.copy()),
        )

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert recorded == [assessment, stats]

    def test_metrics_failure_cannot_change_shadow_result(self, monkeypatch):
        service = MagicMock()
        service.__enter__.return_value = service
        monkeypatch.setattr(
            "app.pipeline_run.record_opportunity_shadow_assessment",
            Mock(side_effect=RuntimeError("metrics failed")),
        )
        monkeypatch.setattr(
            "app.pipeline_run.record_opportunity_shadow_projects",
            Mock(side_effect=RuntimeError("metrics failed")),
        )

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=True,
            sample_rate=1.0,
            service_factory=Mock(return_value=service),
        )

        assert stats["saved"] == 1
        assert stats["failed"] == 0

    @pytest.mark.parametrize(
        ("enabled", "sample_rate", "expected_duration_calls"),
        [(False, 1.0, 0), (True, 0.0, 0), (True, 1.0, 1)],
    )
    def test_records_rollout_summary_on_every_path_and_duration_only_when_sampled(
        self, monkeypatch, enabled, sample_rate, expected_duration_calls
    ):
        summary = Mock()
        duration = Mock(side_effect=RuntimeError("metrics failed"))
        service = MagicMock()
        service.__enter__.return_value = service
        monkeypatch.setattr("app.pipeline_run.record_opportunity_shadow_projects", summary)
        monkeypatch.setattr("app.pipeline_run.observe_opportunity_shadow_duration", duration)

        stats = run_opportunity_shadow(
            [{"id": "project-1", "score": 80}],
            enabled=enabled,
            sample_rate=sample_rate,
            service_factory=Mock(return_value=service),
        )

        summary.assert_called_once_with(stats)
        assert set(summary.call_args.args[0]) == set(EMPTY_SHADOW_STATS)
        assert duration.call_count == expected_duration_calls


def test_sampled_out_rows_do_not_construct_service():
    service_factory = Mock()

    stats = run_opportunity_shadow(
        [{"id": "project-1", "score": 80}],
        enabled=True,
        sample_rate=0.0,
        service_factory=service_factory,
    )

    assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "skipped": 1}
    service_factory.assert_not_called()


def test_invalid_ids_are_eligible_but_skipped_without_service():
    service_factory = Mock()
    rows = [{"id": None, "score": 80}, {"id": "", "score": 70}, {"score": 60}]

    stats = run_opportunity_shadow(rows, enabled=True, sample_rate=1.0, service_factory=service_factory)

    assert stats == {**EMPTY_SHADOW_STATS, "eligible": 3, "skipped": 3}
    service_factory.assert_not_called()


def test_all_in_summary_counts_unscored_rows_as_ineligible():
    rows = [{"id": "one", "score": 80}, {"id": "two", "score": 70}, {"id": "three", "score": None}]
    service = MagicMock()
    service.__enter__.return_value = service

    stats = run_opportunity_shadow(rows, enabled=True, sample_rate=1.0, service_factory=Mock(return_value=service))

    assert stats == {"eligible": 2, "sampled": 2, "attempted": 2, "saved": 2, "failed": 0, "skipped": 0}


@pytest.mark.asyncio
async def test_opportunity_shadow_runs_after_orchestrator(monkeypatch):
    events = []
    rollout_metric = Mock()
    project = RawProject(id="project-1", name="Project One")
    response = SimpleNamespace(
        run_id="run-1",
        status="completed",
        project_count=1,
        states=[],
        errors=[],
        top_score=None,
        persisted_project_rows=[{"id": "project-1", "score": 80}],
    )

    async def fake_orchestrator(**kwargs):
        events.append("legacy-saved")
        return response

    def fake_shadow(rows, *, enabled, sample_rate):
        events.append("shadow-evaluated")
        assert sample_rate == 1.0
        return EMPTY_SHADOW_STATS.copy()

    async def fake_to_thread(function, *args, **kwargs):
        events.append("to-thread")
        return function(*args, **kwargs)

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.set_opportunity_shadow_rollout", rollout_metric)
    monkeypatch.setattr("app.pipeline_run.run_opportunity_shadow", fake_shadow)
    monkeypatch.setattr("app.pipeline_run.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("app.pipeline_run.settings.opportunity_shadow_enabled", True)
    monkeypatch.setattr("app.pipeline_run.settings.opportunity_shadow_sample_rate", 1.0)
    monkeypatch.setattr(
        "app.pipeline_run.CollectorAgent.collect_from_repository",
        lambda self, repo, **kwargs: [project],
    )
    monkeypatch.setattr(
        "app.pipeline_run.mark_successful_raw_projects",
        lambda projects, states, **kwargs: events.append("raw-marked") or 1,
    )
    monkeypatch.setattr(
        "app.pipeline_run.PIPELINE_DURATION.observe",
        lambda duration: events.append("duration-observed"),
    )
    monkeypatch.setattr(
        "app.pipeline_run.PROJECTS_SCORED.inc",
        lambda count: events.append("scored-metric"),
    )
    monkeypatch.setattr("app.pipeline_run.update_db_gauges", lambda conn: events.append("gauges-updated"))
    monkeypatch.setattr("app.pipeline_run.logger.info", lambda event, **kwargs: events.append(event))

    result = await execute_analysis_pipeline(
        projects=None,
        save_to_db=True,
    )

    for legacy_event in (
        "duration-observed",
        "scored-metric",
        "gauges-updated",
        "raw-marked",
        "pipeline.completed",
    ):
        assert events.index(legacy_event) < events.index("to-thread")
    assert events.index("to-thread") < events.index("shadow-evaluated")
    rollout_metric.assert_called_once_with(True, 1.0)
    assert result["opportunity_shadow"] == EMPTY_SHADOW_STATS


@pytest.mark.asyncio
async def test_rollout_metric_failure_preserves_primary_pipeline_response(monkeypatch):
    project = RawProject(id="project-1", name="Project One")
    response = SimpleNamespace(
        run_id="run-1",
        status="completed",
        project_count=1,
        states=[],
        errors=[],
        top_score=None,
        persisted_project_rows=[],
    )

    async def fake_orchestrator(**kwargs):
        return response

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr(
        "app.pipeline_run.set_opportunity_shadow_rollout",
        Mock(side_effect=RuntimeError("metrics failed")),
    )

    result = await execute_analysis_pipeline(projects=[project], save_to_db=False)

    assert result == {
        "run_id": "run-1",
        "status": "completed",
        "project_count": 1,
        "scored_count": 0,
        "error_count": 0,
        # 落库行数现在是响应的一部分：光看 scored_count 无法区分"评分成功且写进去了"
        # 与"评分成功但一行都没写进去"
        "persisted_count": 0,
        "top_score": None,
        "top_projects": [],
        "marked_processed": 0,
        "opportunity_shadow": EMPTY_SHADOW_STATS,
    }


@pytest.mark.asyncio
async def test_shadow_metric_failures_preserve_primary_pipeline_response(monkeypatch):
    project = RawProject(id="project-1", name="Project One")
    assessment = object()
    service = MagicMock()
    service.__enter__.return_value = service
    service.evaluate_row.return_value = assessment
    response = SimpleNamespace(
        run_id="run-1",
        status="completed",
        project_count=1,
        states=[],
        errors=[],
        top_score=None,
        persisted_project_rows=[{"id": "project-1", "score": 80}],
    )

    async def fake_orchestrator(**kwargs):
        return response

    async def fake_to_thread(function, *args, **kwargs):
        return function(*args, service_factory=Mock(return_value=service), **kwargs)

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.asyncio.to_thread", fake_to_thread)
    monkeypatch.setattr("app.pipeline_run.settings.opportunity_shadow_enabled", True)
    monkeypatch.setattr("app.pipeline_run.settings.opportunity_shadow_sample_rate", 1.0)
    for helper in (
        "record_opportunity_shadow_assessment",
        "record_opportunity_shadow_projects",
        "observe_opportunity_shadow_duration",
    ):
        monkeypatch.setattr(f"app.pipeline_run.{helper}", Mock(side_effect=RuntimeError("metrics failed")))

    result = await execute_analysis_pipeline(projects=[project], save_to_db=True)

    assert result == {
        "run_id": "run-1",
        "status": "completed",
        "project_count": 1,
        "scored_count": 0,
        "error_count": 0,
        "persisted_count": 1,
        "top_score": None,
        "top_projects": [],
        "marked_processed": 0,
        "opportunity_shadow": {
            **EMPTY_SHADOW_STATS,
            "eligible": 1,
            "sampled": 1,
            "attempted": 1,
            "saved": 1,
        },
    }


@pytest.mark.asyncio
async def test_opportunity_shadow_does_not_run_without_database_saves(monkeypatch):
    response = SimpleNamespace(
        run_id="run-1",
        status="completed",
        project_count=1,
        states=[],
        errors=[],
        top_score=None,
        persisted_project_rows=[],
    )

    async def fake_orchestrator(**kwargs):
        return response

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.settings.opportunity_shadow_enabled", True)
    to_thread = Mock()
    monkeypatch.setattr("app.pipeline_run.asyncio.to_thread", to_thread)

    await execute_analysis_pipeline(
        projects=[RawProject(id="project-1", name="Project One")],
        save_to_db=False,
    )

    to_thread.assert_not_called()


@pytest.mark.asyncio
async def test_failed_current_save_never_assesses_existing_stale_row(repo_conn, monkeypatch):
    project = RawProject(id="stale-project", name="Current Project")
    state = PipelineState(
        project=project,
        context=AgentContext(run_id="run-1"),
        score=80,
        label="FARM",
        confidence=1.0,
    )
    repo = ProjectRepository(repo_conn)
    stale_state = deepcopy(state)
    stale_state.project.name = "Stale Project"
    repo.save(stale_state)

    def fail_current_save(state):
        raise RuntimeError("current save failed")

    monkeypatch.setattr(repo, "save", fail_current_save)
    monkeypatch.setattr(
        "app.agents.orchestrator_simple.ProjectRepository",
        Mock(return_value=repo),
    )
    orchestrator = SimpleOrchestrator()

    async def return_scored_state(*args, **kwargs):
        return state

    monkeypatch.setattr(orchestrator, "_run_single_project", return_scored_state)
    response = await orchestrator.run_pipeline(
        [project],
        AgentContext(run_id="run-1"),
        save_to_db=True,
    )
    service_factory = Mock()

    stats = run_opportunity_shadow(
        response.persisted_project_rows,
        enabled=True,
        sample_rate=1.0,
        service_factory=service_factory,
    )

    assert response.persisted_project_rows == []
    assert repo.get_by_id("stale-project")["name"] == "Stale Project"
    assert stats == EMPTY_SHADOW_STATS
    service_factory.assert_not_called()


def test_shadow_evaluates_detached_snapshot_after_concurrent_overwrite():
    row = {"id": "project-1", "name": "First", "score": 80, "meta": {"version": 1}}
    service = MagicMock()
    service.__enter__.return_value = service

    stats = run_opportunity_shadow(
        [deepcopy(row)],
        enabled=True,
        sample_rate=1.0,
        service_factory=Mock(return_value=service),
    )
    row["name"] = "Overwritten"
    row["meta"]["version"] = 2

    evaluated = service.evaluate_row.call_args.args[0]
    assert evaluated["name"] == "First"
    assert evaluated["meta"] == {"version": 1}
    assert stats == {**EMPTY_SHADOW_STATS, "eligible": 1, "sampled": 1, "attempted": 1, "saved": 1}


@pytest.mark.asyncio
async def test_empty_run_logs_zero_shadow_completion(monkeypatch):
    events = []
    monkeypatch.setattr(
        "app.pipeline_run.CollectorAgent.collect_from_repository",
        lambda self, repo, **kwargs: [],
    )
    # Disable seed fallback to test the "truly empty" path (B2 adds fallback)
    monkeypatch.setattr("app.pipeline_run.settings.seed_fallback_enabled", False)
    monkeypatch.setattr(
        "app.pipeline_run.logger.info",
        lambda event, **kwargs: events.append((event, kwargs)),
    )

    result = await execute_analysis_pipeline(projects=None)

    assert result["opportunity_shadow"] == EMPTY_SHADOW_STATS
    assert (
        "pipeline.opportunity_shadow_completed",
        {
            "run_id": result["run_id"],
            "eligible": 0,
            "sampled": 0,
            "attempted": 0,
            "saved": 0,
            "failed": 0,
            "skipped": 0,
        },
    ) in events


# ── Task 7: pipeline ProjectRepository economic_replay_enabled wiring ──


@pytest.mark.asyncio
async def test_orchestrator_wires_economic_replay_enabled_from_settings(monkeypatch, repo_conn):
    """Production constructs ProjectRepository(economic_replay_enabled=settings field)."""
    import inspect

    import app.agents.orchestrator_simple as orch_mod

    captured: list[dict] = []

    class TrackingProjectRepository(ProjectRepository):
        def __init__(self, conn=None, *, economic_replay_enabled: bool = False):
            captured.append({"conn": conn, "economic_replay_enabled": economic_replay_enabled})
            super().__init__(conn=conn or repo_conn, economic_replay_enabled=economic_replay_enabled)

        def save_batch_with_rows(self, states):
            return [{"id": s.project.id, "score": s.score} for s in states]

    monkeypatch.setattr(orch_mod, "ProjectRepository", TrackingProjectRepository)
    monkeypatch.setattr(orch_mod.settings, "opportunity_economic_evidence_emit_enabled", True)

    project = RawProject(id="proj-wire-1", name="Wire Test")
    state = PipelineState(
        project=project,
        context=AgentContext(run_id="run-wire"),
        score=80,
        label="FARM",
        confidence=1.0,
    )
    orchestrator = SimpleOrchestrator()

    async def return_state(*args, **kwargs):
        return state

    monkeypatch.setattr(orchestrator, "_run_single_project", return_state)
    await orchestrator.run_pipeline([project], AgentContext(run_id="run-wire"), save_to_db=True)

    assert captured, "ProjectRepository must be constructed"
    # ProjectRepository is called twice: once for sector counts (no flag),
    # once for save (with flag from settings). Check the save call.
    save_calls = [c for c in captured if c["economic_replay_enabled"] is True]
    assert save_calls, f"save path must pass economic_replay_enabled=True, got: {captured}"
    src = inspect.getsource(ProjectRepository.__init__)
    assert "get_settings" not in src


@pytest.mark.asyncio
async def test_orchestrator_replay_flag_off_matches_baseline(monkeypatch, repo_conn):
    """Flag-off serialized pipeline dict equals frozen baseline shape."""
    import app.agents.orchestrator_simple as orch_mod

    monkeypatch.setattr(orch_mod.settings, "opportunity_economic_evidence_emit_enabled", False)

    class LocalRepo(ProjectRepository):
        def __init__(self, conn=None, *, economic_replay_enabled: bool = False):
            assert economic_replay_enabled is False
            super().__init__(conn=conn or repo_conn, economic_replay_enabled=False)

        def save_batch_with_rows(self, states):
            return [{"id": s.project.id, "score": s.score, "name": s.project.name} for s in states]

    monkeypatch.setattr(orch_mod, "ProjectRepository", LocalRepo)

    project = RawProject(id="proj-base-1", name="Baseline")
    state = PipelineState(
        project=project,
        context=AgentContext(run_id="run-base"),
        score=70,
        label="WATCH",
        confidence=0.8,
    )
    orchestrator = SimpleOrchestrator()

    async def return_state(*args, **kwargs):
        return state

    monkeypatch.setattr(orchestrator, "_run_single_project", return_state)
    response = await orchestrator.run_pipeline([project], AgentContext(run_id="run-base"), save_to_db=True)
    payload = response.model_dump()
    # Frozen serialized baseline equality (dynamic run_id / elapsed_ms taken from payload)
    frozen_baseline = {
        "run_id": payload["run_id"],
        "status": "completed",
        "project_count": 1,
        "top_score": 70,
        "elapsed_ms": payload["elapsed_ms"],
        "errors": [],
        "validation_errors": None,
    }
    assert payload == frozen_baseline
    assert "economic" not in payload
    assert "evidence" not in payload


@pytest.mark.asyncio
async def test_post_link_offline_replay_uses_existing_snapshots_no_http(monkeypatch, repo_conn) -> None:
    """After authoritative project save, evidence comes from existing snapshots without HTTP."""
    import app.agents.orchestrator_simple as orch_mod
    from app.opportunity.economic_models import (
        SCHEMA_VERSION,
        EconomicSnapshotRow,
        build_snapshot_id,
        payload_sha256,
    )
    from app.opportunity.economic_repository import EconomicSnapshotRepository
    from app.opportunity.repository import OpportunityRepository
    from app.utils.normalize import create_dedup_key, generate_deterministic_id

    name = "ReplayTarget"
    sector = "L2"
    dedup = create_dedup_key(name, sector).to_string()
    project_id = generate_deterministic_id(create_dedup_key(name, sector))
    payload = {
        "tvl": 2_000_000,
        "change_7d": 0.1,
        "change_7d_unit": "ratio",
        "chains": ["Ethereum"],
        "no_token_yet": False,
    }
    digest = payload_sha256(payload)
    run_id = "daily:2026-07-22:defillama"
    snap_id = build_snapshot_id(
        run_id=run_id,
        source_id="defillama",
        provider_entity_id="raw-replay-1",
        payload_sha256_hex=digest,
    )
    repo_conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at,
            processed, discovery_score, project_id
        ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
        """,
        (
            "raw-replay-1",
            "defillama",
            dedup,
            json.dumps({"name": name, "sector": sector}),
            datetime.now(UTC).isoformat(),
            0.7,
            project_id,
        ),
    )
    snap_repo = EconomicSnapshotRepository(repo_conn)
    snap_repo.insert_if_absent(
        EconomicSnapshotRow(
            snapshot_id=snap_id,
            schema_version=SCHEMA_VERSION,
            run_id=run_id,
            source_id="defillama",
            dedup_key=dedup,
            provider_entity_id="raw-replay-1",
            payload_sha256=digest,
            payload_json=payload,
            source_url="https://api.llama.fi/protocol/example",
            collected_at=datetime(2026, 7, 22, 12, 0, tzinfo=UTC),
        )
    )
    repo_conn.commit()

    monkeypatch.setattr(orch_mod.settings, "opportunity_economic_evidence_emit_enabled", True)

    class WiredRepo(ProjectRepository):
        def __init__(self, conn=None, *, economic_replay_enabled: bool = False):
            super().__init__(conn=conn or repo_conn, economic_replay_enabled=economic_replay_enabled)

    monkeypatch.setattr(orch_mod, "ProjectRepository", WiredRepo)

    project = RawProject(id=project_id, name=name, sector=sector)
    state = PipelineState(
        project=project,
        context=AgentContext(run_id="run-replay"),
        score=85,
        label="FARM",
        confidence=0.95,
    )
    orchestrator = SimpleOrchestrator()

    async def return_state(*args, **kwargs):
        return state

    monkeypatch.setattr(orchestrator, "_run_single_project", return_state)

    with (
        patch("httpx.Client") as http_c,
        patch("httpx.AsyncClient") as http_a,
    ):
        await orchestrator.run_pipeline([project], AgentContext(run_id="run-replay"), save_to_db=True)
    http_c.assert_not_called()
    http_a.assert_not_called()

    evidence = OpportunityRepository(repo_conn).list_evidence(project_id)
    assert len(evidence) >= 1


class TestMarkSuccessfulRawProjects:
    def test_marks_only_scored_projects(self, repo_conn):
        pid_ok = _insert_raw(repo_conn, "r-ok", "OkProj")
        pid_fail = _insert_raw(repo_conn, "r-fail", "FailProj")
        repo = CollectionRepository(repo_conn)

        collector = CollectorAgent()
        projects = collector.collect_from_repository(repo, min_discovery_score=0.0)
        assert len(projects) == 2
        assert all(p.raw_ids for p in projects)

        states = [
            SimpleNamespace(project=SimpleNamespace(id=pid_ok), score=80),
            SimpleNamespace(project=SimpleNamespace(id=pid_fail), score=None),
        ]
        marked = mark_successful_raw_projects(projects, states, repo=repo)
        assert marked >= 1

        rows = {
            r["raw_id"]: r["processed"]
            for r in repo_conn.execute("SELECT raw_id, processed FROM raw_projects").fetchall()
        }
        assert rows["r-ok"] == 1
        assert rows["r-fail"] == 0

    def test_marks_by_raw_ids_when_present(self, repo_conn):
        pid = _insert_raw(repo_conn, "r1", "Solo")
        repo = CollectionRepository(repo_conn)
        raw = RawProject(
            id=pid,
            name="Solo",
            sector="L2",
            raw_ids=["r1"],
            auto_discovered=True,
        )
        states = [SimpleNamespace(project=SimpleNamespace(id=pid), score=70)]
        mark_successful_raw_projects([raw], states, repo=repo)
        processed = repo_conn.execute(
            "SELECT processed FROM raw_projects WHERE raw_id = ?",
            ("r1",),
        ).fetchone()[0]
        assert processed == 1


class TestQueueDrainGuard:
    """队列排空的进程内在飞守卫（见 app/inflight.py 的理由说明）。"""

    @pytest.fixture(autouse=True)
    def _clean_registry(self):
        reset_active_runs()
        yield
        reset_active_runs()

    async def test_concurrent_queue_drains_reject_the_second(self, monkeypatch):
        """两次并发排空：第一次跑完整流程，第二次抛 QueueDrainInProgressError。

        这是 API-4 的核心回归：修复前两次都会真跑，取到重叠的未处理项目
        （processed=1 要等评分结束才写），同一项目被重复评分。
        """
        drain_started = asyncio.Event()
        release_first = asyncio.Event()
        collect_calls = 0

        def fake_collect(self, repo, **kwargs):
            nonlocal collect_calls
            collect_calls += 1
            return [RawProject(id="project-1", name="Project One")]

        async def fake_orchestrator(**kwargs):
            drain_started.set()
            await release_first.wait()
            return SimpleNamespace(
                run_id="run-1",
                status="completed",
                project_count=1,
                states=[],
                errors=[],
                top_score=None,
                persisted_project_rows=[],
            )

        monkeypatch.setattr(
            "app.pipeline_run.CollectorAgent.collect_from_repository",
            fake_collect,
        )
        monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)

        first = asyncio.create_task(execute_analysis_pipeline(projects=None))
        await asyncio.wait_for(drain_started.wait(), timeout=5)

        # 第一次仍在飞（卡在 orchestrator）时发起第二次
        assert QUEUE_DRAIN_KEY in active_runs()
        with pytest.raises(QueueDrainInProgressError):
            await execute_analysis_pipeline(projects=None)

        release_first.set()
        assert (await asyncio.wait_for(first, timeout=5))["run_id"] == "run-1"

        # 被拒的那次绝不能碰队列：只有一次真实读取
        assert collect_calls == 1
        # 守卫已释放，后续运行不受影响
        assert QUEUE_DRAIN_KEY not in active_runs()

    async def test_explicit_projects_bypass_the_guard(self, monkeypatch):
        """显式传 projects 的路径不共享队列，并发无害，不该被挡。"""
        started = asyncio.Event()
        release = asyncio.Event()

        async def fake_orchestrator(**kwargs):
            started.set()
            await release.wait()
            return SimpleNamespace(
                run_id="run-explicit",
                status="completed",
                project_count=1,
                states=[],
                errors=[],
                top_score=None,
                persisted_project_rows=[],
            )

        monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
        project = RawProject(id="project-1", name="Project One")

        first = asyncio.create_task(execute_analysis_pipeline(projects=[project], save_to_db=False))
        await asyncio.wait_for(started.wait(), timeout=5)
        assert not active_runs()

        release.set()
        second = await execute_analysis_pipeline(projects=[project], save_to_db=False)
        assert second["run_id"] == "run-explicit"
        assert (await asyncio.wait_for(first, timeout=5))["run_id"] == "run-explicit"

    async def test_guard_releases_after_pipeline_error(self, monkeypatch):
        """排空抛异常时守卫必须释放，否则一次崩溃会永久锁死队列。"""

        async def boom(**kwargs):
            raise RuntimeError("orchestrator exploded")

        monkeypatch.setattr(
            "app.pipeline_run.CollectorAgent.collect_from_repository",
            lambda self, repo, **kwargs: [RawProject(id="project-1", name="Project One")],
        )
        monkeypatch.setattr("app.pipeline_run.run_orchestrator", boom)

        with pytest.raises(RuntimeError, match="orchestrator exploded"):
            await execute_analysis_pipeline(projects=None)

        assert not active_runs()

    async def test_empty_queue_run_releases_the_guard(self, monkeypatch):
        """空队列提前 return 的分支也要释放（early return 走 contextmanager finally）。"""
        monkeypatch.setattr(
            "app.pipeline_run.CollectorAgent.collect_from_repository",
            lambda self, repo, **kwargs: [],
        )
        # Disable seed fallback to test the "truly empty" path (B2 adds fallback)
        monkeypatch.setattr("app.pipeline_run.settings.seed_fallback_enabled", False)

        result = await execute_analysis_pipeline(projects=None)

        assert result["project_count"] == 0
        assert not active_runs()
