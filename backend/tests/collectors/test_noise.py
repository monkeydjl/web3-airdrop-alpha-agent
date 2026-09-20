"""Shared noise denylist tests."""

from app.collectors.noise import (
    is_listed_brand_subproduct,
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


class TestRwaCredentialFiltering:
    """2026-09 新增：RWA 凭据类资产（封装 BTC / 代币化证券）不是空投候选。

    生产库泄漏样例：WBTC、tzBTC、Stacks sBTC、Bitlayer YBTC Family、
    Function FBTC、Nexus BTC、ObeliskBTC、BitFi BTC、GxBTC、SolvBTC LSTs、
    Starknet BTC Staking、Securitize Tokenized AAA CLO Fund、MatrixDock STBT、
    Bitwise USCC、Spiko、Midas RWA、xStocks、Figure Markets。
    """

    def test_wrapped_btc_credentials_are_noise(self):
        for name, slug in (
            ("WBTC", "wbtc"),
            ("tzBTC", "tzbtc"),
            ("Stacks sBTC", "stacks-sbtc"),
            ("Bitlayer YBTC Family", "bitlayer-ybtc-family"),
            ("Function FBTC", "function-fbtc"),
            ("Nexus BTC", "nexus-btc"),
            ("ObeliskBTC", "obeliskbtc"),
            ("BitFi BTC", "bitfi-btc"),
            ("GxBTC", "gtbtc"),
            ("SolvBTC LSTs", "solvbtc-lsts"),
            ("Starknet BTC Staking", "starknet-btc-staking"),
            ("SUBFROST", "subfrost"),
        ):
            assert is_noise_project(name=name, slug=slug), f"{name} 应被识别为 BTC 凭据"

    def test_tokenized_securities_are_noise(self):
        for name in (
            "Securitize Tokenized AAA CLO Fund",
            "Apollo Diversified Credit Securitize Fund",
            "MatrixDock STBT",
            "Bitwise USCC",
            "Spiko",
            "Midas RWA",
            "xStocks",
            "Figure Markets Democratized Prime",
        ):
            assert is_noise_project(name=name), f"{name} 应被识别为代币化证券凭据"

    def test_rwa_protocols_are_not_noise(self):
        """category=RWA 里的真实 pre-TGE 协议不得被整类误伤。"""
        for name, slug in (
            ("GAIB", "gaib"),
            ("Hastra", "hastra"),
            ("OnRe", "onre"),
            ("Kasu", "kasu"),
        ):
            assert not is_noise_project(name=name, slug=slug, category="RWA"), f"{name} 是真实协议"

    def test_btc_prefixed_names_are_not_noise(self):
        """"BTC" 作前缀的协议名（BTCFi 等）不是 xxxBTC 凭据。"""
        assert not is_noise_project(name="BTCFi CDP", slug="btcfi-cdp", category="CDP")
        assert not is_noise_project(name="Vishwa", slug="vishwa", category="Anchor BTC")
        assert not is_noise_project(name="Chain Fusion", slug="chain-fusion", category="Decentralized BTC")

    def test_midas_brand_without_rwa_not_noise(self):
        """裸 "Midas" 品牌（未来可能的同名新项目）不受 "midas rwa" 误伤。"""
        assert not is_noise_project(name="Midas Protocol", slug="midas-protocol", category="Yield")


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


class TestListedBrandSubproduct:
    """品牌首词匹配：symbol='-' 的子条目，名字首词命中已发币品牌 → 判为品牌子产品。

    起因是 Plume Vaults（2026-09-06）：DefiLlama 上 parentProtocol 为 null、
    symbol='-'，与母条目 "Plume Mainnet"（PLUME 已上市）互不为名字前缀 ——
    采集器既有的前缀规则（"Zircuit Staking" ⊂ "Zircuit"）接不住，它以
    no_token_yet=True 的身份带着 WATCH 65 混进扫描结果。
    """

    def test_plume_vaults_matches_plume_brand(self):
        assert is_listed_brand_subproduct(name="Plume Vaults", slug="plume-vaults") is True

    def test_unknown_brand_stays(self):
        assert is_listed_brand_subproduct(name="Freshchain Vaults", slug="freshchain-vaults") is False

    def test_brand_token_only_matches_at_name_head(self):
        """品牌词只在**首词**上匹配。Mystic Finance myPLUME 的品牌是 Mystic，
        myplume 只是衍生品名 —— 不能因为名字里包含 plume 就误杀。"""
        assert (
            is_listed_brand_subproduct(name="Mystic Finance myPLUME", slug="mystic-finance-myplume")
            is False
        )

    def test_generic_first_token_never_matches(self):
        """首词是通用词（mainnet/finance/swap…）不参与品牌匹配，
        否则 "Mainnet Finance" 会被 "XX Mainnet" 的品牌误伤。"""
        assert is_listed_brand_subproduct(name="Mainnet Finance", slug="mainnet-finance") is False

    def test_short_first_token_never_matches(self):
        """首词过短不匹配 —— 与 _is_facet_of_listed 前缀规则的 ≥3 字符同理，
        避免 "SX" 这类短词误伤。"""
        assert is_listed_brand_subproduct(name="SX Network", slug="sx-network") is False

    def test_static_registry_is_enough_for_known_brands(self):
        """注册表里的品牌不需要额外传参就能命中 —— 采集器和存量追溯脚本
        共用同一份 KNOWN_LISTED_BRANDS。"""
        for brand_name in ("Plume Vaults", "ZKsync Staking", "Berachain Bridge"):
            assert is_listed_brand_subproduct(name=brand_name) is True, brand_name
