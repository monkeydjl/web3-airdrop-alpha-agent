"""Golden test cases for end-to-end pipeline validation.

These cases serve as regression tests to ensure the scoring algorithm
remains consistent and correct. Each case represents a real or realistic
project with expected outputs.

Reference:
- DATA_SCORING_DICT.md §12 (LayerX example)
- ENGINEERING_ROADMAP.md W2-10
"""

from dataclasses import dataclass
from typing import List

from app.agents.base import RawProject


@dataclass
class GoldenCase:
    """A single golden test case.

    Attributes:
        name: Human-readable test case name
        description: Brief description of what this case tests
        project: Input RawProject
        sector_count: Number of projects in this sector (for competition)
        expected_score: Expected final score (±2 tolerance)
        expected_label: Expected label (FARM/WATCH/IGNORE)
        expected_reasons: Expected reason keywords (must match at least 2)
        expected_confidence: Expected confidence (0.0-1.0)
    """

    name: str
    description: str
    project: RawProject
    sector_count: int
    expected_score: int
    expected_label: str
    expected_reasons: List[str]
    expected_confidence: float


# ══════════════════════════════════════════════════════════════
# GOLDEN TEST CASES
# ══════════════════════════════════════════════════════════════

GOLDEN_CASES = [
    # ──────────────────────────────────────────────────────────
    # Case 1: LayerX - High quality project with strong signals
    # ──────────────────────────────────────────────────────────
    GoldenCase(
        name="layerx_high_quality",
        description="High-quality L2 with strong airdrop signals and strong fundamentals",
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
        ),
        sector_count=4,
        expected_score=80,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "credible team"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 2: Restaking Peak - Hot narrative at peak timing
    # ──────────────────────────────────────────────────────────
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
        ),
        sector_count=2,
        expected_score=85,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "peak narrative", "low competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 3: DeFi Mature - Late narrative timing
    # ──────────────────────────────────────────────────────────
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
        expected_score=45,
        expected_label="IGNORE",
        expected_reasons=["no airdrop signal", "late narrative", "high competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 4: Gaming Early - Early stage with moderate signals
    # ──────────────────────────────────────────────────────────
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
        expected_score=64,
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "early narrative"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 5: Infrastructure - Strong fundamentals, low competition
    # ──────────────────────────────────────────────────────────
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
        ),
        sector_count=3,
        expected_score=82,
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "low competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 6: Anonymous Team - High team risk
    # ──────────────────────────────────────────────────────────
    GoldenCase(
        name="anonymous_team_risk",
        description="Project with anonymous team and no URL",
        project=RawProject(
            id="anon-001",
            name="AnonProtocol",
            url=None,  # No URL = anonymous signal
            sector="DeFi",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=True,
            recent_funding=False,
        ),
        sector_count=15,
        expected_score=60,  # Adjusted for team penalty
        expected_label="WATCH",
        expected_reasons=["strong airdrop signal", "team risk"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 7: Ideation Stage - Very early, high uncertainty
    # ──────────────────────────────────────────────────────────
    GoldenCase(
        name="ideation_high_uncertainty",
        description="Ideation-stage project with high uncertainty",
        project=RawProject(
            id="idea-001",
            name="NewConcept",
            url="https://newconcept.xyz",
            sector="NewSector",
            stage="ideation",
            source="seed",
            has_testnet=False,
            has_points_program=False,
            no_token_yet=True,  # Only hint, no points
            recent_funding=True,
        ),
        sector_count=1,
        expected_score=68,  # Low competition boost
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "low competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 8: Bridge - Mature sector with moderate signals
    # ──────────────────────────────────────────────────────────
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
        expected_score=54,  # Actually WATCH, not IGNORE
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "late narrative"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 9: High Competition L2 - Many competitors
    # ──────────────────────────────────────────────────────────
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
        ),
        sector_count=25,
        expected_score=72,  # Strong signals but competition penalty
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "early narrative", "high competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 10: Minimal Signals - Sparse data
    # ──────────────────────────────────────────────────────────
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
        expected_score=45,  # All weak signals
        expected_label="IGNORE",
        expected_reasons=["no airdrop signal", "late narrative", "high competition"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 11: Mixed Signals - Some positive, some negative
    # ──────────────────────────────────────────────────────────
    GoldenCase(
        name="mixed_signals_balanced",
        description="Project with balanced mix of positive and negative signals",
        project=RawProject(
            id="mixed-001",
            name="MixedProtocol",
            url="https://mixed.xyz",
            sector="L2",
            stage="testnet",
            source="seed",
            has_testnet=True,
            has_points_program=True,
            no_token_yet=False,  # Points but no token hint
            recent_funding=False,
        ),
        sector_count=10,
        expected_score=63,  # Balanced
        expected_label="WATCH",
        expected_reasons=["moderate airdrop signal", "early narrative"],
        expected_confidence=1.0,
    ),
    # ──────────────────────────────────────────────────────────
    # Case 12: Funding Boost - Recent funding with strong signals
    # ──────────────────────────────────────────────────────────
    GoldenCase(
        name="recent_funding_boost",
        description="Project with recent funding and strong fundamentals",
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
        ),
        sector_count=3,
        expected_score=81,  # All positive signals
        expected_label="FARM",
        expected_reasons=["strong airdrop signal", "peak narrative", "low competition"],
        expected_confidence=1.0,
    ),
]


def get_golden_case(name: str) -> GoldenCase:
    """Get a golden case by name.

    Args:
        name: Case name

    Returns:
        GoldenCase instance

    Raises:
        ValueError: If case not found
    """
    for case in GOLDEN_CASES:
        if case.name == name:
            return case
    raise ValueError(f"Golden case '{name}' not found")


def get_all_golden_cases() -> List[GoldenCase]:
    """Get all golden cases.

    Returns:
        List of all GoldenCase instances
    """
    return GOLDEN_CASES.copy()
