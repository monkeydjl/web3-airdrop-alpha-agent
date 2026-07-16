"""Shared noise denylist tests."""

from app.collectors.noise import is_noise_project, is_noise_protocol, is_noise_raw_project


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


def test_protocol_and_raw_helpers():
    assert is_noise_protocol({"name": "Uniswap V2", "slug": "uniswap-v2", "category": "Dexs"})
    assert is_noise_raw_project(
        "BingX",
        "Cex",
        {"slug": "bingx", "category": "CEX"},
    )
    assert not is_noise_raw_project("GAIB", "Rwa", {"slug": "gaib"})
