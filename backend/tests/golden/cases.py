"""Golden test cases for end-to-end pipeline validation.

These cases serve as regression tests to ensure the scoring algorithm
remains consistent and correct. Each case represents a real or realistic
project with expected outputs.

Reference:
- DATA_SCORING_DICT.md (v1.2 eight-factor weights)
- ENGINEERING_ROADMAP.md W2-10
"""

from dataclasses import dataclass

from app.agents.base import RawProject


@dataclass
class GoldenCase:
    """A single golden test case."""

    name: str
    description: str
    project: RawProject
    sector_count: int
    expected_score: int
    expected_label: str
    expected_reasons: list[str]
    expected_confidence: float


def _rich(**kwargs) -> dict:
    """Default strong transparency/execution signals for high-quality cases."""
    base = dict(
        has_docs=True,
        has_whitepaper=True,
        has_roadmap=True,
        has_github=True,
        has_twitter=True,
        has_discord=True,
        github_stars=400,
        github_recent_push_days=10,
        explicit_airdrop_mention=False,
    )
    base.update(kwargs)
    return base


GOLDEN_CASES = [
    GoldenCase(
        name="layerx_high_quality",
        description="High-quality L2 with strong airdrop + docs/github (v1.2)",
        project=RawProject(
            id="layerx-001",
            name="LayerX",
            url="https://layerx.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
            **_rich(explicit_airdrop_mention=True),
        ),
        sector_count=4,
        expected_score=83,  # strong signals + execution/transparency
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "active development"],
        expected_confidence=0.907,
    ),
    GoldenCase(
        name="restaking_peak_narrative",
        description="Restaking project at peak narrative timing",
        project=RawProject(
            id="restake-001",
            name="RestakeDAO",
            url="https://restakedao.xyz",
            sector="Restaking",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
            **_rich(github_stars=800, github_recent_push_days=5),
        ),
        sector_count=2,
        expected_score=87,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "peak narrative", "low competition"],
        expected_confidence=0.814,
    ),
    GoldenCase(
        name="defi_mature_late",
        description="Mature DeFi project with late narrative timing",
        project=RawProject(
            id="defi-001",
            name="DeFiSwap",
            url="https://defiswap.xyz",
            sector="DeFi",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=False,
            recent_funding=False,
        ),
        sector_count=20,
        expected_score=46,
        expected_label="IGNORE",
        expected_reasons=["no airdrop signal", "late narrative", "high competition"],
        expected_confidence=0.443,
    ),
    GoldenCase(
        name="gaming_early_moderate",
        description="Early-stage Gaming project with moderate signals",
        project=RawProject(
            id="gaming-001",
            name="GameChain",
            url="https://gamechain.xyz",
            sector="Gaming",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=False,
            recent_funding=False,
        ),
        sector_count=8,
        expected_score=61,
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "early narrative"],
        expected_confidence=0.629,
    ),
    GoldenCase(
        name="infrastructure_strong",
        description="Strong infrastructure project with low competition",
        project=RawProject(
            id="infra-001",
            name="NodeNetwork",
            url="https://nodenetwork.xyz",
            sector="Infrastructure",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
            **_rich(github_stars=600, github_recent_push_days=3),
        ),
        sector_count=3,
        expected_score=84,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "low competition"],
        expected_confidence=0.907,
    ),
    GoldenCase(
        name="anonymous_team_risk",
        description="Project with anonymous team and no URL",
        project=RawProject(
            id="anon-001",
            name="AnonProtocol",
            url=None,
            sector="DeFi",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=False,
        ),
        sector_count=15,
        expected_score=55,
        expected_label="WATCH",
        expected_reasons=["strong airdrop signal", "team risk"],
        expected_confidence=0.536,
    ),
    GoldenCase(
        name="ideation_high_uncertainty",
        description="Ideation-stage project with high uncertainty (v1.2 may stay WATCH)",
        project=RawProject(
            id="idea-001",
            name="NewConcept",
            url="https://newconcept.xyz",
            sector="NewSector",
            stage="ideation",
            source="seed",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=True,
            recent_funding=True,
        ),
        sector_count=1,
        expected_score=57,
        expected_label="IGNORE",
        expected_reasons=["moderate airdrop signal", "low competition"],
        expected_confidence=0.443,
    ),
    GoldenCase(
        name="bridge_mature_moderate",
        description="Bridge project in mature sector",
        project=RawProject(
            id="bridge-001",
            name="CrossBridge",
            url="https://crossbridge.xyz",
            sector="Bridge",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=True,
            no_token_yet=False,
            recent_funding=False,
        ),
        sector_count=12,
        expected_score=54,
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "late narrative"],
        expected_confidence=0.536,
    ),
    GoldenCase(
        name="l2_high_competition",
        description="L2 project in highly competitive market",
        project=RawProject(
            id="l2-comp-001",
            name="L2Competitor",
            url="https://l2comp.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
            **_rich(),
        ),
        sector_count=25,
        expected_score=79,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "active development", "strong public docs"],
        expected_confidence=0.907,
    ),
    GoldenCase(
        name="minimal_signals",
        description="Project with minimal signals and data",
        project=RawProject(
            id="minimal-001",
            name="MinimalProject",
            url="https://minimal.xyz",
            sector="DeFi",
            stage="mainnet",
            source="seed",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=False,
            recent_funding=False,
        ),
        sector_count=18,
        expected_score=46,
        expected_label="IGNORE",
        expected_reasons=["no airdrop signal", "late narrative", "high competition"],
        expected_confidence=0.443,
    ),
    GoldenCase(
        name="mixed_signals_balanced",
        description="Balanced mix — points without no_token stays WATCH under v1.2",
        project=RawProject(
            id="mixed-001",
            name="MixedProtocol",
            url="https://mixed.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=False,
            recent_funding=False,
        ),
        sector_count=10,
        expected_score=62,
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "early narrative"],
        expected_confidence=0.629,
    ),
    GoldenCase(
        name="recent_funding_boost",
        description="Recent funding with strong fundamentals + execution signals",
        project=RawProject(
            id="funded-001",
            name="FundedProtocol",
            url="https://funded.xyz",
            sector="Restaking",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=True,
            **_rich(github_stars=500, github_recent_push_days=7),
        ),
        sector_count=3,
        expected_score=83,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "low competition"],
        expected_confidence=0.907,
    ),
]


def get_all_golden_cases() -> list[GoldenCase]:
    return list(GOLDEN_CASES)


def get_golden_case(name: str) -> GoldenCase:
    for case in GOLDEN_CASES:
        if case.name == name:
            return case
    raise ValueError(f"Golden case not found: {name}")
