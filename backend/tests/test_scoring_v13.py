"""v1.3 scoring: task portal, multi-source evidence, roadmap delivery."""

import pytest

from app.agents.base import AgentContext, PipelineState, RawProject
from app.agents.collector import CollectorAgent
from app.agents.scorer import ScorerAgent
from app.models import NarrativeResult, RiskResult, TeamResult, TokenomicsResult


def test_infer_task_portal_and_delivery():
    flags = CollectorAgent._infer_airdrop_flags(
        "seed",
        {
            "name": "QuestFi",
            "description": "Complete galxe.com quests for points. Roadmap and testnet live.",
            "stage": "testnet",
            "has_testnet": True,
            "url": "https://questfi.xyz",
            "github": "https://github.com/questfi/app",
            "updated_at": "2026-07-01T00:00:00Z",
        },
    )
    assert flags["has_task_portal"] is True
    assert flags["has_roadmap"] is True
    assert flags["roadmap_delivery"] in ("aligned", "partial")


def test_sybil_friction_kyc():
    flags = CollectorAgent._infer_airdrop_flags(
        "seed",
        {"name": "HumanNet", "description": "Requires KYC and World ID for airdrop"},
    )
    assert flags["sybil_friction"] == "high"


@pytest.mark.asyncio
async def test_task_portal_boosts_airdrop_over_wording_only():
    agent = ScorerAgent(sector_counts={"L2": 5})
    base = dict(
        id="a",
        name="P",
        sector="L2",
        stage="testnet",
        source="seed",
        has_testnet=True,
        no_token_yet=True,
        has_points_program=False,
        recent_funding=False,
        explicit_airdrop_mention=False,
    )
    weak = RawProject(**base, has_task_portal=False, source_count=1)
    strong = RawProject(
        **base,
        has_task_portal=True,
        source_count=3,
        has_github=True,
        has_docs=True,
        has_contract=True,
        roadmap_delivery="aligned",
        github_recent_push_days=5,
        github_stars=100,
    )
    ctx = AgentContext(run_id="t")
    s_weak = agent._calc_airdrop_signal(PipelineState(project=weak, context=ctx))
    s_strong = agent._calc_airdrop_signal(PipelineState(project=strong, context=ctx))
    assert s_strong > s_weak
    assert s_strong >= 85 + 14  # base ladder + portal

    full = PipelineState(
        project=strong,
        context=ctx,
        narrative=NarrativeResult(sector="L2", stage="growth", heat_score=0.7, timing="early"),
        team=TeamResult(team_score=0.6, team_flags=[], team_type="semi_anon"),
        risk=RiskResult(token_risk=0.4, risk_flags=[], unlock_pressure="medium"),
        tokenomics=TokenomicsResult(vc_share=0.2, team_share=0.15, unlock_penalty=0.3),
    )
    conf = agent._calc_evidence_confidence(full)
    assert conf >= 0.55  # multi-signal evidence


@pytest.mark.asyncio
async def test_unclear_roadmap_hurts_execution():
    agent = ScorerAgent()
    ctx = AgentContext(run_id="t")
    paper = RawProject(
        id="b",
        name="Paper",
        sector="DeFi",
        stage="ideation",
        source="seed",
        has_roadmap=True,
        roadmap_delivery="unclear",
        has_github=False,
    )
    ship = RawProject(
        id="c",
        name="Ship",
        sector="DeFi",
        stage="testnet",
        source="seed",
        has_roadmap=True,
        roadmap_delivery="aligned",
        has_github=True,
        github_stars=80,
        github_recent_push_days=7,
        has_contract=True,
        has_testnet=True,
    )
    e1 = agent._calc_execution(PipelineState(project=paper, context=ctx))
    e2 = agent._calc_execution(PipelineState(project=ship, context=ctx))
    assert e2 > e1


class TestSiteLivenessSignal:
    """site_alive=False（官网探测到挂了）应扣执行力分；None（没探过）不加分也不加罚。"""

    def test_site_down_penalizes_execution(self):
        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.agents.scorer import ScorerAgent as Agent

        ctx = AgentContext(run_id="r")
        paper = RawProject(
            id="p1", name="Paper", sector="DeFi", stage="mainnet",
            source="defillama", has_roadmap=True, github_recent_push_days=30,
            site_alive=False,  # 探测到官网挂了
        )
        ship = RawProject(
            id="p2", name="Ship", sector="DeFi", stage="mainnet",
            source="defillama", has_roadmap=True, github_recent_push_days=30,
            site_alive=True,
        )
        unprobed = RawProject(
            id="p3", name="Pristine", sector="DeFi", stage="mainnet",
            source="defillama", has_roadmap=True, github_recent_push_days=30,
            site_alive=None,
        )
        agent = Agent()
        ex_dead = agent._calc_execution(PipelineState(project=paper, context=ctx))
        ex_alive = agent._calc_execution(PipelineState(project=ship, context=ctx))
        ex_unprobed = agent._calc_execution(PipelineState(project=unprobed, context=ctx))
        assert ex_dead < ex_alive
        # 没探测过 = 无信息，跟探测到活着同样处理（不能把没探过当坏信号）
        assert ex_unprobed == ex_alive, "site_alive=None 不应被误读成「挂了」"

    @pytest.mark.asyncio
    async def test_site_down_appears_in_reasons(self):
        """被探测到官网挂了必须在最终 reason 里可见（是 forced 理由，
        不能被 top-N 冲掉），否则就只是悄悄的分数惩罚。"""
        from app.agents.base import AgentContext, PipelineState, RawProject
        from app.agents.scorer import ScorerAgent as Agent

        ctx = AgentContext(run_id="r")
        p = RawProject(
            id="p1", name="Dead", sector="DeFi", stage="mainnet",
            source="defillama", site_alive=False,
        )
        state = PipelineState(project=p, context=ctx)
        await Agent().run(state)
        assert any("unreachable" in r for r in (state.reason or [])), (
            "site_alive=False 必须在最终 reason 里可见，不能悄悄只扣了分"
        )

