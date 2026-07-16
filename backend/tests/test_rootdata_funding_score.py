"""Funding fields flow into team / airdrop subscores."""

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.scorer import ScorerAgent
from app.agents.team import infer_team_flags
from app.models import NarrativeResult, RiskResult, TeamResult, TokenomicsResult


def test_tier1_funding_sets_team_flag():
    p = RawProject(
        id="f1",
        name="Funded",
        sector="L2",
        source="rootdata",
        recent_funding=True,
        funding_quality=0.75,
        funding_tier="tier1",
        funding_investors=["a16z", "Paradigm"],
        funding_total_usd=20_000_000,
        funding_rounds=2,
    )
    flags = infer_team_flags(p)
    assert "tier-1 vc backed" in flags


@pytest.mark.asyncio
async def test_funding_lifts_team_and_airdrop_subscores():
    agent = ScorerAgent(sector_counts={"L2": 4})
    ctx = AgentContext(run_id="f")
    plain = RawProject(
        id="a",
        name="Plain",
        sector="L2",
        stage="testnet",
        source="seed",
        has_testnet=True,
        no_token_yet=True,
        recent_funding=False,
        funding_quality=0.0,
    )
    rich = RawProject(
        id="b",
        name="Rich",
        sector="L2",
        stage="testnet",
        source="rootdata",
        has_testnet=True,
        no_token_yet=True,
        recent_funding=True,
        funding_quality=0.8,
        funding_tier="tier1",
        funding_total_usd=30_000_000,
        funding_rounds=3,
        funding_investors=["Paradigm", "a16z"],
        has_docs=True,
        url="https://rich.xyz",
    )
    for p in (plain, rich):
        st = PipelineState(
            project=p,
            context=ctx,
            narrative=NarrativeResult(sector="L2", stage="growth", heat_score=0.7, timing="early"),
            team=TeamResult(team_score=0.55, team_flags=[], team_type="semi_anon"),
            risk=RiskResult(token_risk=0.4, risk_flags=[], unlock_pressure="medium"),
            tokenomics=TokenomicsResult(vc_share=0.25, team_share=0.2, unlock_penalty=0.3),
        )
        if p.name == "Plain":
            air_p = agent._calc_airdrop_signal(st)
            team_p = agent._calc_team_reputation(st)
        else:
            air_r = agent._calc_airdrop_signal(st)
            team_r = agent._calc_team_reputation(st)
    assert air_r >= air_p
    assert team_r > team_p
