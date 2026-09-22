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
async def test_github_curated_collects_core_testnets(curated_collector: GitHubCuratedCollector) -> None:
    # 模拟远程 GitHub raw 失败或超时，内置高置信度测试网库仍应正常输出
    respx.get("https://raw.githubusercontent.com/arddluma/awesome-list-testnet-faucets/main/README.md").mock(
        return_value=Response(404)
    )

    result = await curated_collector.collect()
    assert result.status == "success"
    assert len(result.items) >= 5

    names = {item.name for item in result.items}
    assert "Monad" in names
    assert "Berachain" in names
    assert "Story Protocol" in names
    assert "Babylon" in names

    monad = next(item for item in result.items if item.name == "Monad")
    assert monad.stage == "testnet"
    assert monad.raw_data.get("has_testnet") is True
    assert monad.discovery_score >= 0.5


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
