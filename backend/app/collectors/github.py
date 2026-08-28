"""GitHub Collector.

通过 GitHub Search API 扫描近期活跃的 Web3 早期项目仓库。
返回 RawDiscovery 与原始信号（stars、forks、language、recent activity）。

参考：
- DATA_SOURCE_STRATEGY.md §2. GitHub
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.utils.normalize import normalize_sector

logger = structlog.get_logger(__name__)


def _has_word(text: str, word: str) -> bool:
    """整词匹配，避免 "ai" 命中 blockchain、"l2" 命中 sql2。"""
    return re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) is not None


# Web3-related languages preferred for airdrop discovery
_WEB3_LANGUAGES = {
    "solidity",
    "rust",
    "move",
    "cairo",
    "vyper",
    "haskell",  # cardano-ish
    "go",
    "typescript",
    "javascript",
    "python",
}

# Must hit at least one strong signal in name/description/topics
_WEB3_KEYWORDS = (
    "airdrop",
    "airdrops",
    "testnet",
    "mainnet",
    "points program",
    "loyalty points",
    "zk",
    "rollup",
    "l2",
    "layer2",
    "layer-2",
    "defi",
    "evm",
    "solidity",
    "smart contract",
    "blockchain",
    "web3",
    "crypto",
    "token",
    "nft",
    "restaking",
    "bridge",
    "faucet",
    "dapp",
    "onchain",
    "on-chain",
    "protocol",
    "validator",
    "staking",
)

# Hard denylist: known noise / non-Web3 popular repos that match loose search
_NAME_DENYLIST = {
    "localsend",
    "flyingcarpet",
    "syncthing",
    "homeassistant",
    "nextcloud",
    "points",  # generic word-only repo names often non-Web3
}

_FULL_NAME_DENY_PREFIXES = (
    "microsoft/",
    "google/",
    "facebook/",
    "apple/",
    "torvalds/",
)


class GitHubCollector(DataCollector):
    """GitHub 采集器。

    采集策略：
    1. 使用 GitHub Search API 搜索与空投/测试网/积分相关的仓库
    2. 过滤 stars、语言、关键词相关性与 denylist
    3. 提取仓库元数据与活跃度指标作为信号

    注意：GitHub Search API 对未认证请求限流严格（10 req/min），
    建议配置 GITHUB_TOKEN 以提升配额（30 req/min）。
    """

    STARS_THRESHOLD = 50
    MAX_RESULTS = 30
    SEARCH_WINDOW_DAYS = 90
    # Cap raw discovery score so weak-relevance repos rarely enter analysis (threshold 0.3)
    MAX_DISCOVERY_SCORE = 0.85

    def __init__(self) -> None:
        super().__init__(source_id="github", source_name="GitHub")
        self.base_url = settings.github_api_base_url
        self.timeout = settings.github_timeout
        self.retry = settings.github_retry
        self.rate_limiter = TokenBucketRateLimiter("github")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        # GitHub 搜索需要 token 才能稳定运行；无 token 时默认禁用
        return settings.github_enabled and bool(settings.github_token)

    async def collect(self) -> CollectorResult:
        """执行 GitHub 搜索采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            repos = await self._search_repositories()
            self.logger.info(
                "github.fetched",
                total_repos=len(repos),
            )

            kept = 0
            skipped = 0
            for repo in repos:
                if not self._is_relevant_repo(repo):
                    skipped += 1
                    continue
                discovery = self._build_discovery(repo)
                if discovery is None:
                    skipped += 1
                    continue
                result.items.append(discovery)
                kept += 1
            self.logger.info(
                "github.filtered",
                kept=kept,
                skipped=skipped,
            )

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("github.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _search_repositories(self) -> list[dict[str, Any]]:
        """搜索 GitHub 仓库。

        查询关注：近期更新的、与空投/测试网/积分相关的仓库。
        """
        # 90 天内更新 + 空投相关关键词（OR），并要求最低 stars
        since = (datetime.now(UTC) - timedelta(days=self.SEARCH_WINDOW_DAYS)).strftime("%Y-%m-%d")
        query = f'(airdrop OR testnet OR "points program" OR airdrops) pushed:>{since} stars:>={self.STARS_THRESHOLD}'
        url = f"{self.base_url}/search/repositories"
        params: dict[str, str | int | float | bool | None] = {
            "q": query,
            "sort": "updated",
            "order": "desc",
            "per_page": self.MAX_RESULTS,
        }
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, dict):
            raise ValueError(f"Unexpected GitHub response type: {type(data)}")

        return cast(list[dict[str, Any]], data.get("items", []))

    def _is_relevant_repo(self, repo: dict[str, Any]) -> bool:
        """Noise filter: denylist, language, keyword relevance."""
        if repo.get("fork") is True:
            return False
        if repo.get("archived") is True:
            return False

        name = (repo.get("name") or "").lower()
        full_name = (repo.get("full_name") or "").lower()
        description = (repo.get("description") or "").lower()
        topics = repo.get("topics") or []
        if not isinstance(topics, list):
            topics = []
        topics_text = " ".join(str(t).lower() for t in topics)
        blob = f"{name} {full_name} {description} {topics_text}"

        if name in _NAME_DENYLIST or any(n.strip() == name for n in _NAME_DENYLIST):
            return False
        if any(full_name.startswith(p) for p in _FULL_NAME_DENY_PREFIXES):
            return False

        language = (repo.get("language") or "").lower()
        # Allow unknown language only if strong Web3 keywords present
        has_keyword = any(k in blob for k in _WEB3_KEYWORDS)
        if not has_keyword:
            return False

        if language and language not in _WEB3_LANGUAGES:
            # e.g. Java/C# desktop apps that mention "airdrop" metaphorically
            strong = any(
                k in blob
                for k in (
                    "solidity",
                    "smart contract",
                    "blockchain",
                    "web3",
                    "ethereum",
                    "testnet",
                    "defi",
                    "zk-rollup",
                    "layer2",
                )
            )
            if not strong:
                return False

        return True

    def _relevance_multiplier(self, repo: dict[str, Any]) -> float:
        """Down-weight weak Web3 signal repos (0.4–1.0)."""
        description = (repo.get("description") or "").lower()
        name = (repo.get("name") or "").lower()
        language = (repo.get("language") or "").lower()
        blob = f"{name} {description}"
        score = 0.4
        if language in {"solidity", "cairo", "move", "vyper"}:
            score += 0.35
        elif language in {"rust", "go"}:
            score += 0.2
        if any(k in blob for k in ("airdrop", "testnet", "points program", "faucet")):
            score += 0.25
        if any(k in blob for k in ("defi", "rollup", "zk", "evm", "smart contract")):
            score += 0.15
        return min(1.0, score)

    def _build_discovery(self, repo: dict[str, Any]) -> RawDiscovery | None:
        """把 GitHub 仓库转换为 RawDiscovery。"""
        name = repo.get("name", "")
        if not name:
            return None
        description = repo.get("description") or ""
        url = repo.get("html_url")
        owner = repo.get("owner", {})
        owner_type = owner.get("type", "") if isinstance(owner, dict) else ""

        language = repo.get("language") or "Unknown"
        sector = self._infer_sector(language, description)

        stars = repo.get("stargazers_count") or 0
        forks = repo.get("forks_count") or 0
        open_issues = repo.get("open_issues_count") or 0
        updated_at = repo.get("updated_at")
        created_at = repo.get("created_at")
        rel = self._relevance_multiplier(repo)

        blob = f"{name} {description}".lower()
        has_testnet = "testnet" in blob
        has_points = "points" in blob or "airdrop" in blob
        raw_data = {
            "name": name,
            "url": url,
            "sector": sector,
            "stage": "testnet" if has_testnet else "ideation",
            "repo_id": repo.get("id"),
            "full_name": repo.get("full_name"),
            "description": description,
            "homepage": repo.get("homepage"),
            "language": language,
            "stars": stars,
            "forks": forks,
            "open_issues": open_issues,
            "created_at": created_at,
            "updated_at": updated_at,
            # pushed_at 才是"最后一次提交"。updated_at 会被 star/watch/描述修改顶新，
            # 于是 §5.1b 的 github_recent_push_days（±18 分）量到的是元数据变动而非代码活跃度。
            "pushed_at": repo.get("pushed_at"),
            "owner_type": owner_type,
            "license": repo.get("license", {}).get("key") if repo.get("license") else None,
            "relevance": rel,
            "topics": repo.get("topics") or [],
            "has_testnet": has_testnet,
            "has_points_program": has_points,
            "no_token_yet": "airdrop" in blob or has_testnet,
            "recent_funding": False,
        }

        signals = [
            RawSignal(
                signal_type="github_activity",
                signal_source="github",
                signal_data={
                    "stars": stars,
                    "forks": forks,
                    "open_issues": open_issues,
                    "language": language,
                    "updated_at": updated_at,
                    "relevance": rel,
                },
                signal_strength=self._calculate_activity_strength(stars, forks, updated_at) * rel,
            ),
        ]

        discovery_score = self._calculate_discovery_score(stars, forks, open_issues, updated_at, created_at, language)
        discovery_score = round(min(self.MAX_DISCOVERY_SCORE, discovery_score * rel), 4)
        # Weak relevance → keep as signal-only (below analysis threshold 0.3)
        if rel < 0.55:
            discovery_score = min(discovery_score, 0.28)

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=str(repo.get("id", "")),
            name=name,
            url=url,
            sector=sector,
            stage=raw_data["stage"],
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _infer_sector(self, language: str, description: str) -> str:
        """根据语言与描述推断赛道。"""
        desc_lower = (description or "").lower()
        lang_lower = (language or "").lower()

        if "solidity" in lang_lower or "smart contract" in desc_lower or "defi" in desc_lower:
            return normalize_sector("DeFi")
        # 用词边界而非裸子串：`"l2" in desc` 会命中 "sql2"、"html2md" 之类
        if "rollup" in desc_lower or "layer 2" in desc_lower or _has_word(desc_lower, "l2"):
            return normalize_sector("L2")
        if "restak" in desc_lower:
            return normalize_sector("Restaking")
        if "rust" in lang_lower and ("chain" in desc_lower or "rollup" in desc_lower):
            return normalize_sector("L2")
        # 裸子串 "ai" 会命中 blockchain / chain / mainnet / available / explain…
        # 实测 "Cross-chain bridge SDK"、"A blockchain indexer" 全被判成 AI 赛道。
        # sector 是 dedup_key 的一半，判错既错分类又阻断合并。
        if _has_word(desc_lower, "ai") or _has_word(desc_lower, "ml") or "machine learning" in desc_lower:
            return normalize_sector("AI")
        if "typescript" in lang_lower or "javascript" in lang_lower or "go" in lang_lower:
            return normalize_sector("Infrastructure")
        if "python" in lang_lower:
            return normalize_sector("Infrastructure")
        return normalize_sector("Infrastructure")

    def _calculate_activity_strength(
        self,
        stars: int,
        forks: int,
        updated_at: str | None,
    ) -> float:
        """计算 GitHub 活跃度信号强度。"""
        star_score = min(1.0, stars / 1000)
        fork_score = min(1.0, forks / 200)
        recent_score = 0.5
        if updated_at:
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            days_since = (datetime.now(UTC) - updated).days
            if days_since <= 7:
                recent_score = 1.0
            elif days_since <= 30:
                recent_score = 0.8
            elif days_since <= 90:
                recent_score = 0.5
            else:
                recent_score = 0.2
        return round((star_score * 0.5 + fork_score * 0.2 + recent_score * 0.3), 4)

    def _calculate_discovery_score(
        self,
        stars: int,
        forks: int,
        open_issues: int,
        updated_at: str | None,
        created_at: str | None,
        language: str | None,
    ) -> float:
        """计算发现质量分 0-1。

        维度：
        - stars 规模（35%）
        - forks / 协作度（15%）
        - 近期活跃度（30%）
        - 语言匹配（10%）
        - 仓库成熟度（10%）
        """
        del open_issues  # Retained for compatibility; current weights omit issue count.
        star_score = min(1.0, stars / 1000)
        fork_score = min(1.0, forks / 200)

        recent_score = 0.0
        if updated_at:
            updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            days_since = (datetime.now(UTC) - updated).days
            if days_since <= 7:
                recent_score = 1.0
            elif days_since <= 30:
                recent_score = 0.7
            elif days_since <= 90:
                recent_score = 0.4
            else:
                recent_score = 0.1

        lang_score = 0.0
        if language and language.lower() in {"solidity", "rust", "typescript", "go"}:
            lang_score = 1.0
        elif language and language.lower() in {"python", "javascript", "cairo"}:
            lang_score = 0.6

        maturity_score = 0.5
        if created_at:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            age_days = (datetime.now(UTC) - created).days
            if 30 <= age_days <= 365:
                maturity_score = 1.0  # 1 年以内的新项目，空投概率高
            elif age_days < 30:
                maturity_score = 0.5  # 太新，可信度低
            else:
                maturity_score = 0.3

        score = star_score * 0.35 + fork_score * 0.15 + recent_score * 0.30 + lang_score * 0.10 + maturity_score * 0.10
        return round(score, 4)

    async def health_check(self) -> dict[str, Any]:
        """检查 GitHub API 可用性。"""
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                headers = {"Accept": "application/vnd.github+json"}
                if settings.github_token:
                    headers["Authorization"] = f"Bearer {settings.github_token}"
                response = await client.get(
                    f"{self.base_url}/rate_limit",
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                remaining = data.get("resources", {}).get("search", {}).get("remaining", 0)
                return {
                    "source_id": self.source_id,
                    "status": "healthy",
                    "search_remaining": remaining,
                }
        except Exception as e:
            return {
                "source_id": self.source_id,
                "status": "unhealthy",
                "error": str(e),
            }
