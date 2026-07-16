"""Tests for GitHub collector.

使用 respx mock GitHub Search API。
"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.collectors.github import GitHubCollector
from app.config import settings


@pytest.fixture
def github_collector(monkeypatch) -> GitHubCollector:
    """创建 GitHub 采集器，并确保 token 存在以启用。"""
    monkeypatch.setattr(settings, "github_token", "ghp_test_token")
    monkeypatch.setattr(settings, "github_enabled", True)
    return GitHubCollector()


@respx.mock
def test_github_collector_enabled(github_collector: GitHubCollector) -> None:
    """有 token 时采集器应启用。"""
    assert github_collector.is_enabled()


@respx.mock
def test_github_collector_disabled_without_token(monkeypatch) -> None:
    """无 token 时采集器应禁用。"""
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_enabled", True)
    collector = GitHubCollector()
    assert not collector.is_enabled()


@respx.mock
async def test_github_collect_success(github_collector: GitHubCollector) -> None:
    """模拟 GitHub 搜索返回一个仓库。"""
    route = respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(
            200,
            json={
                "total_count": 1,
                "items": [
                    {
                        "id": 12345,
                        "name": "AirdropAlpha",
                        "full_name": "org/AirdropAlpha",
                        "html_url": "https://github.com/org/AirdropAlpha",
                        "description": "A testnet points protocol for airdrops",
                        "language": "Solidity",
                        "stargazers_count": 250,
                        "forks_count": 40,
                        "open_issues_count": 12,
                        "created_at": "2024-01-15T00:00:00Z",
                        "updated_at": "2024-07-08T00:00:00Z",
                        "owner": {"type": "Organization"},
                        "license": {"key": "mit"},
                    },
                ],
            },
        )
    )

    result = await github_collector.collect()

    assert result.status in {"success", "partial"}
    assert len(result.items) == 1
    assert route.called

    discovery = result.items[0]
    assert discovery.name == "AirdropAlpha"
    assert discovery.source_id == "github"
    assert discovery.discovery_score > 0
    assert len(discovery.raw_signals) == 1


@respx.mock
async def test_github_collect_empty(github_collector: GitHubCollector) -> None:
    """搜索返回空列表。"""
    route = respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(200, json={"total_count": 0, "items": []})
    )

    result = await github_collector.collect()

    assert result.status == "partial"
    assert len(result.items) == 0
    assert route.called


@respx.mock
async def test_github_collect_error(github_collector: GitHubCollector) -> None:
    """GitHub API 返回错误。"""
    respx.get("https://api.github.com/search/repositories").mock(
        return_value=Response(403, json={"message": "rate limit exceeded"})
    )

    result = await github_collector.collect()

    assert result.status == "error"
    assert result.error_message is not None


def test_github_infer_sector(github_collector: GitHubCollector) -> None:
    """推断赛道。"""
    assert github_collector._infer_sector("Solidity", "DeFi protocol") == "DeFi"
    assert github_collector._infer_sector("Rust", "Layer 2 rollup") == "L2"
    assert github_collector._infer_sector("TypeScript", "frontend") == "Infrastructure"
    assert github_collector._infer_sector("Go", "node") == "Infrastructure"
    assert github_collector._infer_sector("Python", "AI agent") == "AI"
    assert github_collector._infer_sector("Unknown", "") == "Infrastructure"


def test_github_filters_noise_repos(github_collector: GitHubCollector) -> None:
    """无关仓库应被噪声过滤掉。"""
    assert not github_collector._is_relevant_repo(
        {
            "name": "LocalSend",
            "full_name": "localsend/localsend",
            "description": "share files with airdrop-like UX",
            "language": "Dart",
            "fork": False,
        }
    )
    assert github_collector._is_relevant_repo(
        {
            "name": "AirdropAlpha",
            "full_name": "org/AirdropAlpha",
            "description": "A testnet points protocol for airdrops",
            "language": "Solidity",
            "fork": False,
            "topics": ["defi"],
        }
    )


def test_github_discovery_score(github_collector: GitHubCollector) -> None:
    """discovery_score 计算在合理范围。"""
    score = github_collector._calculate_discovery_score(
        stars=2000,
        forks=300,
        open_issues=50,
        updated_at="2026-07-08T00:00:00Z",
        created_at="2025-12-15T00:00:00Z",
        language="Solidity",
    )
    assert 0 <= score <= 1
    assert score > 0.5


def test_github_activity_strength(github_collector: GitHubCollector) -> None:
    """活跃度信号强度计算。"""
    strength = github_collector._calculate_activity_strength(
        stars=500,
        forks=100,
        updated_at="2024-07-08T00:00:00Z",
    )
    assert 0 <= strength <= 1


@respx.mock
async def test_github_health_check(github_collector: GitHubCollector) -> None:
    """健康检查。"""
    respx.get("https://api.github.com/rate_limit").mock(
        return_value=Response(
            200,
            json={
                "resources": {
                    "search": {"remaining": 20, "limit": 30},
                },
            },
        )
    )

    health = await github_collector.health_check()

    assert health["source_id"] == "github"
    assert health["status"] == "healthy"
    assert health["search_remaining"] == 20
