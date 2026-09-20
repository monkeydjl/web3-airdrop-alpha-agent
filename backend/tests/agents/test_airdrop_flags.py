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


class TestCompletedAirdropGate:
    """2026-09 修复：回顾性空投文本不得推断出 explicit_airdrop_mention。

    "airdrop" 与 "snapshot"/"eligible" 的共现在回顾性报道里同样成立
    （"符合条件的用户已领取"），不设负向门控会让已发币项目借文本残留
    通过 is_listed_token_no_airdrop_signals 与 eligibility veto。
    """

    def test_completed_airdrop_text_does_not_set_explicit(self):
        flags = CollectorAgent._infer_airdrop_flags(
            "medium",
            {
                "name": "ZK Rollup Recap",
                "description": "the airdrop completed in June 2024; eligible wallets claimed their allocation",
            },
        )
        assert flags["explicit_airdrop_mention"] is False

    def test_claim_window_closed_does_not_set_explicit(self):
        flags = CollectorAgent._infer_airdrop_flags(
            "medium",
            {"name": "X", "description": "airdrop claim window closed; snapshot was taken last month"},
        )
        assert flags["explicit_airdrop_mention"] is False

    def test_upcoming_airdrop_text_still_sets_explicit(self):
        flags = CollectorAgent._infer_airdrop_flags(
            "medium",
            {
                "name": "X",
                "description": "airdrop confirmed; snapshot expected next month and eligible users will receive tokens",
            },
        )
        assert flags["explicit_airdrop_mention"] is True

    def test_explicit_field_wins_over_completed_text(self):
        """显式字段是刻意输入，优先于文本推断（含负向门控）。"""
        flags = CollectorAgent._infer_airdrop_flags(
            "seed",
            {"name": "X", "description": "airdrop completed", "explicit_airdrop_mention": True},
        )
        assert flags["explicit_airdrop_mention"] is True
