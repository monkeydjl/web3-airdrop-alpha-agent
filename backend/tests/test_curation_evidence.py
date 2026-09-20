"""Tests for curation evidence generation (精选活动证据链路).

Reference:
- backend/app/services/curation_evidence.py
- backend/app/services/project_signals.py::curation_reasons
"""

from datetime import UTC, datetime

from app.agents.base import AgentContext, PipelineState, RawProject
from app.services.curation_evidence import build_curation_evidence


def make_state(**project_kwargs: object) -> PipelineState:
    project = RawProject(id="test-001", name="Test Project", **project_kwargs)  # type: ignore[arg-type]
    context = AgentContext(run_id="test-run-001", enable_llm=False)
    state = PipelineState(project=project, context=context)
    state.score = 85
    state.label = "FARM"
    state.confidence = 0.9
    state.reason = ["strong signal"]
    return state


def test_recent_github_push_becomes_development_evidence():
    state = make_state(
        url="https://github.com/org/repo",
        has_github=True,
        github_recent_push_days=3,
    )
    evidence = build_curation_evidence(state)
    assert len(evidence) == 1
    item = evidence[0]
    assert item["kind"] == "development"
    assert item["source"] == "github"
    assert item["url"] == "https://github.com/org/repo"
    occurred = datetime.fromisoformat(item["occurred_at"])
    assert (datetime.now(UTC) - occurred).days == 3


def test_active_task_portal_becomes_campaign_evidence():
    state = make_state(
        url="https://galxe.com/space/campaign/123",
        has_task_portal=True,
    )
    evidence = build_curation_evidence(state)
    assert len(evidence) == 1
    item = evidence[0]
    assert item["kind"] == "campaign"
    assert item["source"] == "galxe"
    assert item["status"] == "active"
    checked = datetime.fromisoformat(item["checked_at"])
    assert (datetime.now(UTC) - checked).total_seconds() < 60


def test_no_verifiable_signals_yields_no_evidence():
    state = make_state(url="https://defillama.com/protocol/ghost", has_github=False)
    assert build_curation_evidence(state) == []
