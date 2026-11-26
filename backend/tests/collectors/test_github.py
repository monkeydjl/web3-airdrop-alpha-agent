"""Tests for GitHub collector.

使用 respx mock GitHub Search API。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response
from structlog.testing import capture_logs

from app.collectors.github import GitHubCollector
from app.config import settings

_SEARCH_URL = "https://api.github.com/search/repositories"

_REPO_ITEM = {
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
}


class _NoopRateLimiter:
    """测试用：跳过令牌桶等待，避免重试用例被 1 rps 拖慢。"""

    async def __aenter__(self) -> _NoopRateLimiter:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _search_ok() -> Response:
    return Response(200, json={"total_count": 1, "items": [_REPO_ITEM]})


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
def test_github_collector_enabled_without_token(monkeypatch) -> None:
    """无 token 但 github_enabled=True 时采集器支持未认证公开搜索。"""
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_enabled", True)
    collector = GitHubCollector()
    assert collector.is_enabled()


@respx.mock
def test_github_collector_disabled_when_not_enabled(monkeypatch) -> None:
    """github_enabled 为 False 时采集器禁用。"""
    monkeypatch.setattr(settings, "github_enabled", False)
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


def test_github_filters_tooling_repos(github_collector: GitHubCollector) -> None:
    """撸毛脚本 / bot / 水龙头仓库不是项目（2026-10-06，生产库 15 条 github 源全是这类）。"""
    for repo in (
        {
            "name": "Pharos-Auto-Bot",
            "full_name": "vikitoshi/Pharos-Auto-Bot",
            "description": "An automated bot for interacting with the Pharos Testnet",
            "language": "JavaScript",
            "topics": ["airdrop", "pharos-testnet-bot"],
        },
        {
            "name": "particle-testnet-bot",
            "full_name": "dante4rt/particle-testnet-bot",
            "description": "automating transactions on the Ethereum testnet using multiple private keys",
            "language": "JavaScript",
        },
        {
            "name": "solana-devnet-faucet",
            "full_name": "solana-developers/solana-devnet-faucet",
            "description": "Public web faucet for Solana devnet/testnet airdrops",
            "language": "TypeScript",
        },
    ):
        assert not github_collector._is_relevant_repo({**repo, "fork": False}), repo["name"]


def test_github_raw_data_does_not_assert_token_or_points(github_collector: GitHubCollector) -> None:
    """仓库文本给不出发币/积分证据：raw_data 不再显式写 no_token_yet / has_points_program。

    显式字段在 _infer_airdrop_flags 里优先级最高，此前 "airdrop" 一词就让仓库
    变成「有积分、未发币」，下游无从纠正。
    """
    disc = github_collector._build_discovery(
        {
            "id": 1,
            "name": "AirdropAlpha",
            "full_name": "org/AirdropAlpha",
            "html_url": "https://github.com/org/AirdropAlpha",
            "description": "A testnet points protocol for airdrops",
            "language": "Solidity",
            "stargazers_count": 250,
            "forks_count": 40,
            "created_at": "2026-01-15T00:00:00Z",
            "updated_at": "2026-09-08T00:00:00Z",
        }
    )
    assert disc is not None
    assert "no_token_yet" not in disc.raw_data
    assert "has_points_program" not in disc.raw_data


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


# ── GITHUB_RETRY：可重试失败退避重试，不可重试失败立即失败 ──────────


@pytest.fixture
def retrying_collector(monkeypatch) -> GitHubCollector:
    """无 token、GITHUB_RETRY=2（总尝试 3 次）；退避置 0 以免拖慢测试。"""
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_enabled", True)
    monkeypatch.setattr(settings, "github_retry", 2)
    collector = GitHubCollector()
    collector.rate_limiter = _NoopRateLimiter()  # type: ignore[assignment]
    collector.RETRY_BASE_DELAY = 0.0
    return collector


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (400, False),
        (401, False),
        (403, False),
        (404, False),
    ],
)
def test_github_retryable_status_matrix(status_code: int, expected: bool) -> None:
    assert GitHubCollector._is_retryable_status(status_code) is expected


@respx.mock
async def test_github_retries_5xx_then_succeeds(retrying_collector: GitHubCollector) -> None:
    route = respx.get(_SEARCH_URL).mock(side_effect=[Response(502), _search_ok()])

    with capture_logs() as logs:
        result = await retrying_collector.collect()

    assert result.status == "success"
    assert len(result.items) == 1
    assert route.call_count == 2
    retry_events = [event for event in logs if event["event"] == "collector.retry"]
    assert len(retry_events) == 1
    assert retry_events[0]["attempt"] == 1
    assert retry_events[0]["max_attempts"] == 3


@respx.mock
async def test_github_retries_429_then_succeeds(retrying_collector: GitHubCollector) -> None:
    route = respx.get(_SEARCH_URL).mock(side_effect=[Response(429, headers={"Retry-After": "0"}), _search_ok()])

    result = await retrying_collector.collect()

    assert result.status == "success"
    assert route.call_count == 2


@respx.mock
async def test_github_retries_transport_error_then_succeeds(retrying_collector: GitHubCollector) -> None:
    route = respx.get(_SEARCH_URL).mock(side_effect=[httpx.ConnectError("connection reset"), _search_ok()])

    result = await retrying_collector.collect()

    assert result.status == "success"
    assert route.call_count == 2


@respx.mock
async def test_github_does_not_retry_403(retrying_collector: GitHubCollector) -> None:
    route = respx.get(_SEARCH_URL).mock(return_value=Response(403, json={"message": "rate limit exceeded"}))

    result = await retrying_collector.collect()

    assert result.status == "error"
    assert route.call_count == 1


@respx.mock
async def test_github_retry_exhausted_returns_error(retrying_collector: GitHubCollector) -> None:
    route = respx.get(_SEARCH_URL).mock(return_value=Response(500))

    result = await retrying_collector.collect()

    assert result.status == "error"
    assert result.error_message is not None
    assert "500" in result.error_message
    assert route.call_count == 3  # 1 次首发 + 2 次重试


@respx.mock
async def test_github_zero_retry_single_attempt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_enabled", True)
    monkeypatch.setattr(settings, "github_retry", 0)
    collector = GitHubCollector()
    collector.rate_limiter = _NoopRateLimiter()  # type: ignore[assignment]
    route = respx.get(_SEARCH_URL).mock(return_value=Response(500))

    result = await collector.collect()

    assert result.status == "error"
    assert route.call_count == 1


def test_github_retry_delay_backoff_and_caps() -> None:
    """退避翻倍 + 抖动（[d, d + 0.5d]），Retry-After 取大不抖动，封顶 RETRY_MAX_DELAY。

    2026-11-13：网络退避加抖动后不再是确定值（防多任务同时失败时齐射重试）
    —— 断言区间而非精确值；Retry-After 是上游明确指令，保持精确。
    """
    collector = GitHubCollector()

    for attempt, base in ((1, 1.0), (2, 2.0), (3, 4.0)):
        delay = collector._retry_delay(attempt, None)
        assert base <= delay <= base * 1.5, f"attempt={attempt}: {delay} 不在 [d, d + 0.5d] 区间"

    assert collector._retry_delay(1, 5.0) == 5.0  # Retry-After 大于退避时取它（不抖动）
    assert collector._retry_delay(1, 600.0) == collector.RETRY_MAX_DELAY
    assert collector._retry_delay(100, None) == collector.RETRY_MAX_DELAY


def test_github_retry_after_header_parsing() -> None:
    assert GitHubCollector._retry_after_seconds(Response(429, headers={"Retry-After": "7"})) == 7.0
    assert GitHubCollector._retry_after_seconds(Response(429)) is None
    # HTTP-date 形式不解析，退回指数退避，避免把日期当秒数睡死
    assert (
        GitHubCollector._retry_after_seconds(Response(429, headers={"Retry-After": "Wed, 21 Oct 2015 07:28:00 GMT"}))
        is None
    )
