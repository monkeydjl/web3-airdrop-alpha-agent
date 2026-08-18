"""Tests for UnifiedScheduler (B3, §11).

Covers:
- Skip-if-running: when a queue drain is in progress, the second trigger is skipped + logged
- No overlap: concurrent analysis triggers never produce overlapping runs
- Unified lifecycle: single start/shutdown covers both collection + analysis jobs
- Job registration: both collection and analysis jobs registered on single scheduler
- Manual trigger: trigger_analysis_now / trigger_collection_now work

Reference:
- V2_TASKS.md B3
- ENGINEERING_ROADMAP.md §11 调度
- ADR-005 APScheduler 内嵌调度
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import settings
from app.inflight import QUEUE_DRAIN_KEY, active_runs, claim_run, reset_active_runs
from app.scheduler import UnifiedScheduler


# ── Fixtures ──────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_inflight():
    reset_active_runs()
    yield
    reset_active_runs()


def _make_fake_registry():
    """Build a fake registry with no enabled collectors (tests focus on analysis)."""
    registry = MagicMock()
    registry.list_enabled.return_value = []
    registry.get.return_value = None
    return registry


# ── Skip-if-running ─────────────────────────────


@pytest.mark.asyncio
async def test_skip_if_running_when_drain_in_progress(monkeypatch):
    """When QUEUE_DRAIN_KEY is in active_runs(), _run_analysis skips and logs."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    # Simulate a drain already in progress
    with claim_run(QUEUE_DRAIN_KEY) as acquired:
        assert acquired
        assert QUEUE_DRAIN_KEY in active_runs()

        events: list[str] = []
        mock_logger = MagicMock(
            info=lambda event, **kw: events.append(event),
            warning=lambda event, **kw: events.append(event),
            error=lambda event, **kw: events.append(event),
        )
        # _logger is bound in __init__; must patch the instance attribute
        monkeypatch.setattr(sched, "_logger", mock_logger)

        await sched._run_analysis()

    assert "unified_scheduler.analysis_skipped" in events
    # execute_analysis_pipeline should NOT have been called
    assert "unified_scheduler.analysis_started" not in events


@pytest.mark.asyncio
async def test_skip_if_running_logs_reason(monkeypatch):
    """The skip log includes the reason and guard key."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    captured: list[dict] = []
    mock_logger = MagicMock(
        info=lambda event, **kw: captured.append({"event": event, **kw}),
        warning=lambda event, **kw: captured.append({"event": event, **kw}),
        error=lambda event, **kw: captured.append({"event": event, **kw}),
    )
    monkeypatch.setattr(sched, "_logger", mock_logger)

    with claim_run(QUEUE_DRAIN_KEY):
        await sched._run_analysis()

    skip_logs = [e for e in captured if e["event"] == "unified_scheduler.analysis_skipped"]
    assert len(skip_logs) == 1
    assert skip_logs[0]["reason"] == "queue_drain_in_progress"
    assert skip_logs[0]["guard_key"] == QUEUE_DRAIN_KEY


@pytest.mark.asyncio
async def test_no_overlap_concurrent_triggers(monkeypatch):
    """Two concurrent _run_analysis calls: one runs, the other is skipped."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    drain_started = asyncio.Event()
    release_drain = asyncio.Event()
    call_count = 0

    async def fake_pipeline(**kwargs):
        nonlocal call_count
        call_count += 1
        # Simulate the real pipeline's claim_run behavior so the guard works
        from app.inflight import QUEUE_DRAIN_KEY as QDK

        with claim_run(QDK) as acquired:
            assert acquired
            drain_started.set()
            await release_drain.wait()
        return {
            "run_id": "test-run",
            "status": "completed",
            "project_count": 0,
            "scored_count": 0,
            "persisted_count": 0,
        }

    monkeypatch.setattr("app.scheduler.execute_analysis_pipeline", fake_pipeline)
    monkeypatch.setattr("app.scheduler.update_db_gauges", lambda conn: None)

    # Start first analysis (will block on release_drain)
    task1 = asyncio.create_task(sched._run_analysis())
    await asyncio.wait_for(drain_started.wait(), timeout=5)

    # While first is running, start second — should be skipped
    task2 = asyncio.create_task(sched._run_analysis())
    result2 = await asyncio.wait_for(task2, timeout=5)

    # Second should have returned None (skipped, no exception)
    assert result2 is None
    assert call_count == 1  # Only one pipeline execution

    # Release the first
    release_drain.set()
    await asyncio.wait_for(task1, timeout=5)

    assert call_count == 1  # Still only one


# ── Unified lifecycle ──────────────────────────


@pytest.mark.asyncio
async def test_start_registers_both_collection_and_analysis_jobs(monkeypatch):
    """Unified scheduler registers collection jobs + analysis job on a single AsyncIOScheduler."""
    # Build a fake registry with one enabled collector
    fake_collector = MagicMock()
    fake_collector.is_enabled.return_value = True
    fake_collector.source_id = "defillama"

    registry = MagicMock()
    registry.list_enabled.return_value = [fake_collector]
    registry.get.return_value = fake_collector

    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "collection_scheduler_enabled", True)

    sched = UnifiedScheduler(registry)
    sched.start()

    try:
        jobs = sched.scheduler.get_jobs()
        job_ids = [j.id for j in jobs]

        # Collection job registered
        assert any(j.startswith("collect_") for j in job_ids), f"No collection jobs: {job_ids}"
        # Analysis job registered
        assert "analysis_run_queue" in job_ids, f"No analysis job: {job_ids}"
    finally:
        sched.shutdown(wait=False)


@pytest.mark.asyncio
async def test_start_disabled_when_both_flags_off(monkeypatch):
    """When both scheduler_enabled and collection_scheduler_enabled are False, no jobs registered."""
    registry = _make_fake_registry()
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "collection_scheduler_enabled", False)

    sched = UnifiedScheduler(registry)
    sched.start()

    assert not sched.scheduler.running


@pytest.mark.asyncio
async def test_shutdown_is_noop_when_not_started():
    """shutdown() on a non-started scheduler is a no-op (no SchedulerNotRunningError)."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)
    sched.shutdown()  # Should not raise


# ── Analysis execution ─────────────────────────


@pytest.mark.asyncio
async def test_analysis_runs_when_not_in_progress(monkeypatch):
    """When no drain is in progress, _run_analysis executes the pipeline."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    called = False

    async def fake_pipeline(**kwargs):
        nonlocal called
        called = True
        return {
            "run_id": "test-run",
            "status": "completed",
            "project_count": 5,
            "scored_count": 3,
            "persisted_count": 3,
        }

    monkeypatch.setattr("app.scheduler.execute_analysis_pipeline", fake_pipeline)
    monkeypatch.setattr("app.scheduler.update_db_gauges", lambda conn: None)

    await sched._run_analysis()

    assert called


@pytest.mark.asyncio
async def test_analysis_failure_records_pipeline_run(monkeypatch):
    """When _run_analysis catches an exception (not QueueDrainInProgressError), it records the run."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    async def boom(**kwargs):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("app.scheduler.execute_analysis_pipeline", boom)

    recorded: list[dict] = []

    def fake_record(*, run_id, trigger, duration_ms, summary, error=None, **kw):
        recorded.append({
            "run_id": run_id,
            "trigger": trigger,
            "error": error,
            "summary": summary,
        })

    monkeypatch.setattr("app.scheduler.record_pipeline_run", fake_record)

    await sched._run_analysis()

    assert len(recorded) == 1
    assert recorded[0]["trigger"] == "cron"
    assert "pipeline exploded" in recorded[0]["error"]


@pytest.mark.asyncio
async def test_race_condition_falls_back_to_exception(monkeypatch):
    """If QUEUE_DRAIN_KEY is acquired between the check and the call, QueueDrainInProgressError is caught."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    from app.inflight import QueueDrainInProgressError

    call_count = 0

    async def fake_pipeline(**kwargs):
        nonlocal call_count
        call_count += 1
        raise QueueDrainInProgressError("race condition")

    monkeypatch.setattr("app.scheduler.execute_analysis_pipeline", fake_pipeline)

    events: list[str] = []
    mock_logger = MagicMock(
        info=lambda event, **kw: events.append(event),
        warning=lambda event, **kw: events.append(event),
        error=lambda event, **kw: events.append(event),
    )
    monkeypatch.setattr(sched, "_logger", mock_logger)

    await sched._run_analysis()

    assert call_count == 1
    assert "unified_scheduler.analysis_skipped" in events


# ── Manual triggers ─────────────────────────────


@pytest.mark.asyncio
async def test_trigger_analysis_now(monkeypatch):
    """trigger_analysis_now calls execute_analysis_pipeline with trigger='manual'."""
    registry = _make_fake_registry()
    sched = UnifiedScheduler(registry)

    captured_trigger = None

    async def fake_pipeline(*, trigger=None, **kwargs):
        nonlocal captured_trigger
        captured_trigger = trigger
        return {"run_id": "manual", "status": "completed", "project_count": 0}

    monkeypatch.setattr("app.scheduler.execute_analysis_pipeline", fake_pipeline)

    result = await sched.trigger_analysis_now()

    assert captured_trigger == "manual"
    assert result["status"] == "completed"


# ── Job diagnostics ─────────────────────────────


@pytest.mark.asyncio
async def test_get_jobs_returns_unified_list(monkeypatch):
    """get_jobs() returns both collection and analysis jobs in a single list."""
    fake_collector = MagicMock()
    fake_collector.is_enabled.return_value = True
    fake_collector.source_id = "github"

    registry = MagicMock()
    registry.list_enabled.return_value = [fake_collector]
    registry.get.return_value = fake_collector

    monkeypatch.setattr(settings, "scheduler_enabled", True)
    monkeypatch.setattr(settings, "collection_scheduler_enabled", True)

    sched = UnifiedScheduler(registry)
    sched.start()
    try:
        jobs = sched.get_jobs()
        job_ids = [j["id"] for j in jobs]

        assert "collect_github" in job_ids
        assert "analysis_run_queue" in job_ids
    finally:
        sched.shutdown(wait=False)
