"""Tests for GitHubCuratedCollector."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.collectors.github_curated import GitHubCuratedCollector
from app.config import settings


@pytest.fixture
def curated_collector(monkeypatch) -> GitHubCuratedCollector:
    monkeypatch.setattr(settings, "github_enabled", True)
    return GitHubCuratedCollector()


def test_github_curated_enabled(curated_collector: GitHubCuratedCollector) -> None:
    assert curated_collector.is_enabled()


def test_github_curated_disabled_when_config_false(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_enabled", False)
    collector = GitHubCuratedCollector()
    assert not collector.is_enabled()


@respx.mock
async def test_github_curated_remote_failure_yields_no_stale_entries(
    curated_collector: GitHubCuratedCollector,
) -> None:
    """远程失败时不再回退到写死的「测试网」清单（2026-10-06）。

    原内置 9 条（Monad / Berachain / Babylon …）逐个核实已 TGE，却以
    no_token_yet=True 每天入库。清单清空后，远程失败 = 本轮无产出。
    """
    respx.get("https://raw.githubusercontent.com/arddluma/awesome-list-testnet-faucets/main/README.md").mock(
        return_value=Response(404)
    )

    result = await curated_collector.collect()
    assert result.status == "partial"
    assert result.items == []


def test_curated_entry_defaults_to_listed(curated_collector: GitHubCuratedCollector) -> None:
    """未写明 no_token_yet 的条目按已发币处理，不能被假定为 pre-TGE。"""
    disc = curated_collector._build_from_curated_entry({"name": "Freshchain", "sector": "L1"})
    assert disc is not None
    assert disc.raw_data["no_token_yet"] is False


@respx.mock
async def test_github_curated_remote_listed_brand_not_pre_tge(curated_collector: GitHubCuratedCollector) -> None:
    """水龙头清单里的已发币品牌（Monad）不得以 no_token_yet=True 入库。"""
    mock_md = "- [Monad](https://monad.xyz) - [Faucet](https://faucet.monad.xyz)\n- [Freshchain](https://fresh.xyz)"
    respx.get("https://raw.githubusercontent.com/arddluma/awesome-list-testnet-faucets/main/README.md").mock(
        return_value=Response(200, text=mock_md)
    )

    result = await curated_collector.collect()
    by_name = {item.name: item for item in result.items}
    assert by_name["Monad"].raw_data["no_token_yet"] is False
    assert by_name["Freshchain"].raw_data["no_token_yet"] is True


@respx.mock
async def test_github_curated_parses_remote_markdown(curated_collector: GitHubCuratedCollector) -> None:
    mock_md = """
    # Awesome Testnet Faucets
    - [Plume Network](https://plumenetwork.xyz) - [Testnet Faucet](https://faucet.plumenetwork.xyz)
    - [Fuel](https://fuel.network) - [Faucet Link](https://faucet-testnet.fuel.network)
    """
    respx.get("https://raw.githubusercontent.com/arddluma/awesome-list-testnet-faucets/main/README.md").mock(
        return_value=Response(200, text=mock_md)
    )

    result = await curated_collector.collect()
    assert result.status == "success"
    names = {item.name for item in result.items}
    assert "Plume Network" in names
    plume = next(item for item in result.items if item.name == "Plume Network")
    assert plume.raw_data.get("has_testnet") is True
    assert plume.raw_data.get("faucet_url") == "https://faucet.plumenetwork.xyz"
