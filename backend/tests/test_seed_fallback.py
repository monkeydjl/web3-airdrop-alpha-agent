"""Tests for seed fallback module (B2, §10.2).

Covers:
- get_seed_raw_projects(): returns non-empty, source='seed', created_at=None
- Seed dataset diversity: multiple sectors, funding clues for token_risk
- Pipeline fallback: when collect_from_repository returns empty and
  seed_fallback_enabled=True, seed projects flow through the pipeline
- Pipeline no-fallback: when seed_fallback_enabled=False, returns empty
- DB persistence: seed projects written with source='seed', fetched_at=NULL

Reference:
- V2_TASKS.md B2
- ENGINEERING_ROADMAP.md §10.2「Collector 全量失败回退 seed」
"""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.db import init_db
from app.inflight import reset_active_runs
from app.pipeline_run import execute_analysis_pipeline
from app.repository import ProjectRepository
from app.seed import SEED_PROJECTS, get_seed_raw_projects

# ── Unit tests: get_seed_raw_projects ──────────


def test_get_seed_raw_projects_returns_nonempty():
    projects = get_seed_raw_projects()
    assert len(projects) > 0


def test_seed_projects_source_is_seed():
    projects = get_seed_raw_projects()
    for p in projects:
        assert p.source == "seed", f"Project {p.name} has source={p.source}, expected 'seed'"


def test_seed_projects_created_at_is_none():
    """created_at=None maps to fetched_at=NULL in DB (§5 table comment)."""
    projects = get_seed_raw_projects()
    for p in projects:
        assert p.created_at is None, f"Project {p.name} has created_at={p.created_at}, expected None"


def test_seed_projects_have_diverse_sectors():
    projects = get_seed_raw_projects()
    sectors = {p.sector for p in projects if p.sector}
    assert len(sectors) >= 5, f"Expected >=5 sectors, got {sectors}"


def test_seed_projects_have_funding_clues():
    """At least some seed projects carry funding data for token_risk heuristics (§6.5)."""
    projects = get_seed_raw_projects()
    with_funding = [p for p in projects if p.funding_total_usd and p.funding_total_usd > 0]
    assert len(with_funding) >= 3, f"Expected >=3 projects with funding, got {len(with_funding)}"

    # At least one tier1 investor
    tier1 = [p for p in projects if p.funding_tier == "tier1"]
    assert len(tier1) >= 1

    # At least one with lead investors
    with_leads = [p for p in projects if p.funding_lead_investors]
    assert len(with_leads) >= 1


def test_seed_projects_have_dedup_ids():
    """All seed projects should have unique deterministic IDs after dedup."""
    projects = get_seed_raw_projects()
    ids = [p.id for p in projects]
    assert len(ids) == len(set(ids)), "Duplicate project IDs found"


def test_seed_projects_have_airdrop_signals():
    """Seed data should include projects with various airdrop signal combinations."""
    projects = get_seed_raw_projects()
    has_testnet = [p for p in projects if p.has_testnet]
    has_points = [p for p in projects if p.has_points_program]
    no_token = [p for p in projects if p.no_token_yet]

    assert len(has_testnet) >= 1, "Expected at least one testnet project"
    assert len(has_points) >= 1, "Expected at least one points program project"
    assert len(no_token) >= 1, "Expected at least one no-token-yet project"


def test_seed_dataset_count():
    """Seed dataset has at least 8 projects for meaningful demo."""
    assert len(SEED_PROJECTS) >= 8


# ── Pipeline integration: fallback on empty repository ──────────


@pytest.fixture(autouse=True)
def _clean_inflight():
    reset_active_runs()
    yield
    reset_active_runs()


@pytest.mark.asyncio
async def test_pipeline_fallback_loads_seed_when_repository_empty(monkeypatch):
    """When collect_from_repository returns [] and fallback enabled, seed projects are used."""
    monkeypatch.setattr(
        "app.pipeline_run.CollectorAgent.collect_from_repository",
        lambda self, repo, **kwargs: [],
    )

    captured_projects: list[RawProject] = []

    async def fake_orchestrator(*, projects, run_id, **kwargs):
        captured_projects.extend(projects)
        return SimpleNamespace(
            run_id=run_id,
            status="completed",
            project_count=len(projects),
            states=[],
            errors=[],
            top_score=None,
            persisted_project_rows=[],
        )

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.update_db_gauges", lambda conn: None)

    result = await execute_analysis_pipeline(projects=None, save_to_db=False)

    assert result["project_count"] > 0
    assert len(captured_projects) > 0

    # Verify seed projects were loaded
    for p in captured_projects:
        assert p.source == "seed"
        assert p.created_at is None


@pytest.mark.asyncio
async def test_pipeline_no_fallback_when_disabled(monkeypatch):
    """When seed_fallback_enabled=False, empty repository returns empty result."""
    monkeypatch.setattr(
        "app.pipeline_run.CollectorAgent.collect_from_repository",
        lambda self, repo, **kwargs: [],
    )
    monkeypatch.setattr("app.pipeline_run.settings.seed_fallback_enabled", False)

    result = await execute_analysis_pipeline(projects=None, save_to_db=False)

    assert result["project_count"] == 0
    assert "No projects to score" in result["message"]


@pytest.mark.asyncio
async def test_pipeline_fallback_log_emitted(monkeypatch):
    """Seed fallback activation is logged as a warning."""
    monkeypatch.setattr(
        "app.pipeline_run.CollectorAgent.collect_from_repository",
        lambda self, repo, **kwargs: [],
    )

    events: list[str] = []

    def capture_warning(event, **kwargs):
        events.append(event)

    monkeypatch.setattr("app.pipeline_run.logger.warning", capture_warning)

    async def fake_orchestrator(**kwargs):
        return SimpleNamespace(
            run_id="run-seed",
            status="completed",
            project_count=8,
            states=[],
            errors=[],
            top_score=None,
            persisted_project_rows=[],
        )

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.update_db_gauges", lambda conn: None)

    await execute_analysis_pipeline(projects=None, save_to_db=False)

    assert "pipeline.seed_fallback_activated" in events


# ── DB persistence: source='seed', fetched_at=NULL ──────────


def test_seed_project_persists_with_null_fetched_at():
    """A RawProject with source='seed' and created_at=None persists with fetched_at=NULL."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        repo = ProjectRepository(conn=conn)

        project = RawProject(
            id="seed-test-001",
            name="Seed Test Project",
            url="https://seed-test.example.com",
            sector="DeFi",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            created_at=None,  # seed data: no fetch → NULL fetched_at
        )
        state = PipelineState(
            project=project,
            context=AgentContext(run_id="test-run"),
            score=75,
            label="FARM",
            confidence=0.8,
            reason="Strong airdrop signals",
        )

        repo.save(state)
        row = conn.execute(
            "SELECT source, fetched_at FROM projects WHERE id = ?",
            ("seed-test-001",),
        ).fetchone()

        assert row["source"] == "seed"
        assert row["fetched_at"] is None
    finally:
        conn.close()


def test_seed_project_funding_data_persists():
    """Seed projects with funding clues persist correctly for token_risk heuristics."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        repo = ProjectRepository(conn=conn)

        project = RawProject(
            id="seed-fund-001",
            name="Funding Test",
            sector="L2",
            stage="testnet",
            source="seed",
            funding_total_usd=50_000_000,
            funding_rounds=3,
            funding_lead_investors=["a16z"],
            funding_tier="tier1",
            funding_quality=0.8,
            created_at=None,
        )
        state = PipelineState(
            project=project,
            context=AgentContext(run_id="test-run"),
            score=80,
            label="FARM",
            confidence=0.9,
            reason="Tier1 funding",
        )

        repo.save(state)
        row = conn.execute(
            "SELECT source, fetched_at, meta FROM projects WHERE id = ?",
            ("seed-fund-001",),
        ).fetchone()

        assert row["source"] == "seed"
        assert row["fetched_at"] is None
    finally:
        conn.close()


# ── Edge cases ──────────


def test_get_seed_raw_projects_idempotent():
    """Calling get_seed_raw_projects twice returns same deterministic IDs."""
    first = get_seed_raw_projects()
    second = get_seed_raw_projects()

    assert [p.id for p in first] == [p.id for p in second]


@pytest.mark.asyncio
async def test_explicit_projects_skip_fallback(monkeypatch):
    """When projects are explicitly passed, seed fallback is not triggered."""
    explicit = RawProject(id="explicit-1", name="Explicit Project", source="manual")

    fallback_called = False

    def spy_get_seed():
        nonlocal fallback_called
        fallback_called = True
        return []

    monkeypatch.setattr("app.pipeline_run.get_seed_raw_projects", spy_get_seed)

    async def fake_orchestrator(**kwargs):
        return SimpleNamespace(
            run_id="run-1",
            status="completed",
            project_count=1,
            states=[],
            errors=[],
            top_score=None,
            persisted_project_rows=[],
        )

    monkeypatch.setattr("app.pipeline_run.run_orchestrator", fake_orchestrator)
    monkeypatch.setattr("app.pipeline_run.update_db_gauges", lambda conn: None)

    await execute_analysis_pipeline(projects=[explicit], save_to_db=False)

    assert not fallback_called, "Seed fallback should not trigger when explicit projects are passed"
