"""Unit tests for dashboard daily flash endpoint and scheduled collector registrations."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.collectors.factory import build_default_registry
from app.main import app
from app.scheduler import UnifiedScheduler


def test_get_daily_flash_endpoint() -> None:
    client = TestClient(app)
    res = client.get("/api/v1/dashboard/daily-flash")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    inner = data["data"]
    assert "date" in inner
    assert "active_farm_count" in inner
    assert "ticker_text" in inner
    assert "⚡ 今日 Alpha 速递" in inner["ticker_text"]
    assert len(inner["highlights"]) >= 2


def test_unified_scheduler_registers_curated_and_digest() -> None:
    registry = build_default_registry()
    sched = UnifiedScheduler(registry)

    # Inspect cron map and ensure github_curated is in collection jobs
    sched._register_collection_jobs()
    job_ids = [j.id for j in sched.scheduler.get_jobs()]
    assert "collect_github_curated" in job_ids

    # Inspect alpha digest job
    sched._register_alpha_digest_job()
    job_ids = [j.id for j in sched.scheduler.get_jobs()]
    assert "daily_alpha_digest" in job_ids
