"""Shared noise denylist tests."""

from app.collectors.noise import (
    is_listed_token_no_airdrop_signals,
    is_noise_project,
    is_noise_protocol,
    is_noise_raw_project,
)


def test_cex_and_bluechips_are_noise():
    assert is_noise_project(name="BingX", category="CEX")
    assert is_noise_project(name="Zoomex", category="Derivatives")
    assert is_noise_project(name="Uniswap V4", slug="uniswap-v4")
    assert is_noise_project(name="Aave V3", slug="aave-v3")
    assert is_noise_project(name="Coinbase Bridge", slug="coinbase-bridge")
    assert is_noise_project(name="BlackRock BUIDL")
    assert is_noise_project(name="Yearn Finance")
    assert is_noise_project(name="EtherFi Cash Liquid")
    assert is_noise_project(name="WisdomTree")


def test_early_defi_not_noise():
    assert not is_noise_project(name="Nova Vault", slug="nova-vault", category="Yield")
    assert not is_noise_project(name="TermMax", slug="termmax", category="Lending")
    assert not is_noise_project(name="T3tris Finance", slug="t3tris", category="Yield")


def test_crypto_com_products_are_noise():
    """CDC 质押/LSDFi 产品线：成熟品牌，无空投 alpha（2026-09 泄漏样例）。"""
    assert is_noise_project(name="Crypto.com Liquid Staking", category="Liquid Staking")
    assert not is_noise_project(name="CryptoNative Vault", category="Yield")


def test_protocol_and_raw_helpers():
    assert is_noise_protocol({"name": "Uniswap V2", "slug": "uniswap-v2", "category": "Dexs"})
    assert is_noise_raw_project(
        "BingX",
        "Cex",
        {"slug": "bingx", "category": "CEX"},
    )
    assert not is_noise_raw_project("GAIB", "Rwa", {"slug": "gaib"})


class TestListedTokenNoAirdropSignals:
    def test_listed_token_with_no_signals(self):
        """Project with listed token and zero airdrop signals should be filtered."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=False,
                has_testnet=False,
                has_points_program=False,
                has_task_portal=False,
                explicit_airdrop_mention=False,
                source_id="defillama",
            )
            is True
        )

    def test_unlisted_token_kept(self):
        """Project without a token yet should NOT be filtered."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=True,
                has_testnet=False,
                has_points_program=False,
                has_task_portal=False,
                explicit_airdrop_mention=False,
                source_id="defillama",
            )
            is False
        )

    def test_listed_token_with_testnet_kept(self):
        """Listed token but has testnet = potential airdrop, keep it."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=False,
                has_testnet=True,
                source_id="defillama",
            )
            is False
        )

    def test_listed_token_with_points_kept(self):
        """Listed token but has points program = potential airdrop, keep it."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=False,
                has_points_program=True,
                source_id="defillama",
            )
            is False
        )

    def test_listed_token_with_quest_kept(self):
        """Listed token but has quest portal = potential airdrop, keep it."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=False,
                has_task_portal=True,
                source_id="defillama",
            )
            is False
        )

    def test_signal_supplement_sources_exempt(self):
        """Signal supplement sources should never be filtered."""
        for source_id in ("coingecko", "cryptorank", "etherscan", "alchemy_webhook"):
            assert (
                is_listed_token_no_airdrop_signals(
                    no_token_yet=False,
                    has_testnet=False,
                    has_points_program=False,
                    has_task_portal=False,
                    explicit_airdrop_mention=False,
                    source_id=source_id,
                )
                is False
            )

    def test_listed_token_with_airdrop_mention_kept(self):
        """Listed token but has explicit airdrop mention = keep it."""
        assert (
            is_listed_token_no_airdrop_signals(
                no_token_yet=False,
                explicit_airdrop_mention=True,
                source_id="twitter_kol",
            )
            is False
        )
