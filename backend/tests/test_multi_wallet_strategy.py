"""Tests for multi-wallet strategy recommendation engine (US-019 / Roadmap W12-01)."""

from __future__ import annotations

from app.agents.base import RawProject
from app.services.multi_wallet_strategy import generate_multi_wallet_strategy


def _proj(**updates: object) -> RawProject:
    values: dict[str, object] = {
        "id": "strategy-01",
        "name": "AlphaProtocol",
        "sector": "L2",
        "stage": "mainnet",
        "source": "seed",
        "no_token_yet": True,
        "has_testnet": True,
        "has_points_program": True,
    }
    values.update(updates)
    return RawProject(**values)  # type: ignore[arg-type]


def test_ineligible_project_recommends_zero_wallets() -> None:
    # Case 1: IGNORE
    p = _proj(id="p-ignore")
    data = p.to_dict()
    data["label"] = "IGNORE"
    strategy = generate_multi_wallet_strategy(data)

    assert strategy.status == "ineligible"
    assert strategy.recommended_wallets_optimal == 0
    assert strategy.tier == "not_recommended"
    assert strategy.total_capital_usd_max == 0.0
    assert len(strategy.hygiene_guidelines) == 0

    # Case 2: explicit_no_airdrop veto
    p2 = _proj(id="p-no-drop", explicit_no_airdrop=True)
    data2 = p2.to_dict()
    data2["veto"] = "explicit_no_airdrop"
    strategy2 = generate_multi_wallet_strategy(data2)
    assert strategy2.status == "ineligible"
    assert strategy2.recommended_wallets_optimal == 0


def test_selective_watchlist_recommends_single_observational_wallet() -> None:
    p = _proj(id="p-watch", has_testnet=False, has_points_program=False)
    data = p.to_dict()
    data["label"] = "WATCH"
    data["veto"] = "no_participation_path"

    strategy = generate_multi_wallet_strategy(data)
    assert strategy.status == "selective"
    assert strategy.recommended_wallets_min == 1
    assert strategy.recommended_wallets_max == 2
    assert strategy.recommended_wallets_optimal == 1
    assert strategy.tier == "single_curated"


def test_high_sybil_friction_recommends_single_curated_wallets() -> None:
    p = _proj(
        id="p-high-sybil",
        sybil_friction="high",
        description="decentralized identity requiring gitcoin passport and kyc verification",
    )
    strategy = generate_multi_wallet_strategy(p)

    assert strategy.status == "recommended"
    assert strategy.recommended_wallets_min == 1
    assert strategy.recommended_wallets_max == 2
    assert strategy.recommended_wallets_optimal == 1
    assert strategy.tier == "single_curated"
    assert "精品主号" in strategy.tier_zh
    assert any(g["severity"] == "critical" for g in strategy.hygiene_guidelines)


def test_medium_sybil_friction_recommends_small_cluster() -> None:
    p = _proj(
        id="p-medium-sybil",
        sybil_friction="medium",
        sector="L2",
        stage="mainnet",
    )
    strategy = generate_multi_wallet_strategy(p)

    assert strategy.status == "recommended"
    assert strategy.recommended_wallets_min == 3
    assert strategy.recommended_wallets_max == 5
    assert strategy.recommended_wallets_optimal == 3
    assert strategy.tier == "small_cluster"
    assert "小梯队" in strategy.tier_zh


def test_low_sybil_testnet_recommends_wider_scale() -> None:
    p = _proj(
        id="p-low-testnet",
        sybil_friction="low",
        stage="testnet",
        has_testnet=True,
    )
    strategy = generate_multi_wallet_strategy(p)

    assert strategy.status == "recommended"
    assert strategy.recommended_wallets_min == 5
    assert strategy.recommended_wallets_max == 10
    assert strategy.recommended_wallets_optimal == 5
    assert strategy.tier == "medium_scale"
    # Testnet cost should be minimal
    assert strategy.capital_per_wallet_usd_min == 0.0
    assert strategy.capital_per_wallet_usd_max <= 5.0


def test_perp_dex_mainnet_requires_higher_capital_reserve() -> None:
    p = _proj(
        id="p-perp",
        sector="perp-dex",
        stage="mainnet",
        description="decentralized perpetual futures exchange",
        sybil_friction="medium",
    )
    strategy = generate_multi_wallet_strategy(p)

    assert strategy.capital_per_wallet_usd_min >= 50.0
    assert strategy.total_capital_usd_min >= 150.0
    assert any("Perp DEX" in w for w in strategy.risk_warnings)


def test_hygiene_guidelines_contain_critical_rules() -> None:
    p = _proj(id="p-rules", sybil_friction="medium")
    strategy = generate_multi_wallet_strategy(p)

    rule_ids = [r["rule_id"] for r in strategy.hygiene_guidelines]
    assert "zero_wallet_transfer" in rule_ids
    assert "temporal_dispersion" in rule_ids
    assert "path_differentiation" in rule_ids
    assert "environment_isolation" in rule_ids

