"""ADR-015 eligibility-veto behavior."""

from __future__ import annotations

import asyncio

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.eligibility import (
    VETO_ALREADY_LAUNCHED,
    VETO_NO_PARTICIPATION_PATH,
    apply_eligibility_gate,
    is_already_launched_without_airdrop_path,
)
from app.agents.scorer import ScorerAgent
from app.models import NarrativeResult, RiskResult, TeamResult, TokenomicsResult


def _state(project: RawProject) -> PipelineState:
    return PipelineState(
        project=project,
        context=AgentContext(run_id="eligibility-test"),
        narrative=NarrativeResult(sector="L2", stage="early", heat_score=1.0, timing="early"),
        team=TeamResult(team_score=0.95, team_flags=[], team_type="doxxed"),
        risk=RiskResult(token_risk=0.0, risk_flags=[], unlock_pressure="low"),
        tokenomics=TokenomicsResult(vc_share=0.0, team_share=0.0, unlock_penalty=0.0),
    )


def _strong_project(**overrides: object) -> RawProject:
    values: dict[str, object] = {
        "id": "eligibility-project",
        "name": "Eligibility Project",
        "sector": "L2",
        "no_token_yet": True,
        "has_testnet": True,
        "has_points_program": True,
        "has_task_portal": True,
        "has_docs": True,
        "has_whitepaper": True,
        "has_roadmap": True,
        "has_github": True,
        "has_twitter": True,
        "has_discord": True,
        "github_stars": 2000,
        "github_recent_push_days": 1,
        "has_contract": True,
        "source_count": 3,
        "roadmap_delivery": "aligned",
    }
    values.update(overrides)
    return RawProject(**values)  # type: ignore[arg-type]


def test_already_launched_veto_downgrades_farm_without_changing_score() -> None:
    project = _strong_project(
        no_token_yet=False,
        has_testnet=False,
        has_points_program=False,
        has_task_portal=False,
        explicit_airdrop_mention=False,
    )
    state = _state(project)
    scorer = ScorerAgent(sector_counts={"L2": 1})

    baseline_score = scorer._calculate_total_score(scorer._calculate_subscores(state))
    assert scorer._score_to_label(baseline_score) == "FARM"

    scored = asyncio.run(scorer.run(state))

    assert scored.score == baseline_score
    assert scored.label == "IGNORE"
    assert scored.veto == VETO_ALREADY_LAUNCHED
    assert scored.reason[0].startswith("token already launched")


def test_launch_veto_is_shared_with_airdrop_signal_cap() -> None:
    launched = _strong_project(
        no_token_yet=False,
        has_points_program=False,
        has_task_portal=False,
        explicit_airdrop_mention=False,
    )
    exempt = _strong_project(no_token_yet=False, has_points_program=True)

    assert is_already_launched_without_airdrop_path(launched) is True
    assert is_already_launched_without_airdrop_path(exempt) is False


def test_post_launch_points_explicit_or_portal_exempt_the_veto() -> None:
    for override in (
        {"has_points_program": True},
        {"explicit_airdrop_mention": True},
        {"has_task_portal": True},
    ):
        values = {
            "no_token_yet": False,
            "has_testnet": False,
            "has_points_program": False,
            "has_task_portal": False,
            "explicit_airdrop_mention": False,
        }
        values.update(override)
        project = _strong_project(**values)
        decision = apply_eligibility_gate(project, "FARM")
        assert decision.veto != VETO_ALREADY_LAUNCHED
        assert decision.label in {"FARM", "WATCH"}


def test_no_participation_path_downgrades_only_farm_to_watch() -> None:
    project = _strong_project(has_testnet=False, has_points_program=False, has_task_portal=False)

    decision = apply_eligibility_gate(project, "FARM")
    assert decision.label == "WATCH"
    assert decision.veto == VETO_NO_PARTICIPATION_PATH

    assert apply_eligibility_gate(project, "WATCH").label == "WATCH"
    assert apply_eligibility_gate(project, "IGNORE").label == "IGNORE"
