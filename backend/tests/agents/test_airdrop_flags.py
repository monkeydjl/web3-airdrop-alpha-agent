"""Tests for CollectorAgent airdrop flag inference from raw_projects."""

from app.agents.collector import CollectorAgent


def test_defillama_unlisted_sets_no_token():
    flags = CollectorAgent._infer_airdrop_flags(
        "defillama",
        {"name": "Alpha", "sector": "L2", "stage": "testnet", "gecko_id": None},
    )
    assert flags["no_token_yet"] is True
    assert flags["has_testnet"] is True


def test_defillama_explicit_flags_win():
    flags = CollectorAgent._infer_airdrop_flags(
        "defillama",
        {
            "no_token_yet": False,
            "has_testnet": True,
            "has_points_program": True,
            "gecko_id": None,
        },
    )
    assert flags["no_token_yet"] is False
    assert flags["has_points_program"] is True


def test_coingecko_listed_not_no_token():
    flags = CollectorAgent._infer_airdrop_flags(
        "coingecko",
        {"name": "Bitcoin", "symbol": "BTC"},
    )
    assert flags["no_token_yet"] is False


def test_github_text_hints():
    flags = CollectorAgent._infer_airdrop_flags(
        "github",
        {
            "name": "CoolAirdrop",
            "description": "testnet points program for early users",
        },
    )
    assert flags["has_testnet"] is True
    assert flags["has_points_program"] is True
    assert flags["no_token_yet"] is True
