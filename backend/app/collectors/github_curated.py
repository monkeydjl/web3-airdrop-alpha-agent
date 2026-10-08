"""GitHub Curated Alpha Collector.

同步与抓取 GitHub 开源社区维护的 Web3 零成本测试网、水龙头与空投教程。
完全采用免 Token 公开内容端点，为系统源源不断注入最新测试网早期项目。

参考：
- DATA_SOURCE_STRATEGY.md
- ACTION_LOOP_DESIGN.md
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.noise import is_listed_brand_subproduct
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.utils.normalize import normalize_sector
from app.utils.redact import redact

logger = structlog.get_logger(__name__)

# 知名社区高星开源测试网与水龙头列表（公开 raw 内容端点，免 Token、免鉴权）
DEFAULT_REMOTE_CURATED_URLS = [
    "https://raw.githubusercontent.com/arddluma/awesome-list-testnet-faucets/main/README.md",
]

# 内置精选测试网清单（当远程受阻或离线时作为高置信度基底）。
#
# 2026-10-06 清空：原先 9 条（Monad / Berachain / Story / Babylon / Movement /
# Initia / Soneium / MegaETH / Nesa）全部写死 no_token_yet=True，但逐个核实后
# 8 个早已 TGE（最早 Movement 2024-12，最晚 Nesa 2026-06），Soneium 官方表示
# 无原生代币计划、主网 2025-01 已上线。静态清单不会自己过期，留着就是每天
# 往库里灌「已发币项目伪装成测试网机会」。
#
# 新增条目的门槛：必须核实**当前**仍未发币，并显式写 no_token_yet（缺省按
# 已发币处理），注释里注明核实日期与依据。
CORE_CURATED_TESTNETS: list[dict[str, Any]] = []


class GitHubCuratedCollector(DataCollector):
    """GitHub 社区精选测试网与空投库采集器。"""

    def __init__(self) -> None:
        super().__init__(source_id="github_curated", source_name="GitHub Curated Testnets")
        self.timeout = 20
        self.rate_limiter = TokenBucketRateLimiter("github")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.github_enabled)

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        items_map: dict[str, RawDiscovery] = {}

        # 1. 首先加载内置权威测试网列表作为高置信度基底
        for entry in CORE_CURATED_TESTNETS:
            disc = self._build_from_curated_entry(entry)
            if disc:
                items_map[disc.name.lower()] = disc

        # 2. 尝试从远程公开开源仓库更新 Markdown 列表
        try:
            remote_items = await self._fetch_remote_curated_lists()
            for disc in remote_items:
                name_key = disc.name.lower()
                if name_key not in items_map:
                    items_map[name_key] = disc
            self.logger.info(
                "github_curated.fetched_remote",
                remote_count=len(remote_items),
                total_candidates=len(items_map),
            )
        except Exception as e:
            self.logger.warning("github_curated.remote_fetch_warning", error=redact(str(e)))

        result.items = sorted(items_map.values(), key=lambda x: x.discovery_score, reverse=True)
        result.status = "success" if result.items else "partial"
        result.finished_at = datetime.now(UTC)
        return result

    def _build_from_curated_entry(self, entry: dict[str, Any]) -> RawDiscovery | None:
        name = entry.get("name")
        if not name:
            return None

        sector = normalize_sector(entry.get("sector") or "Infrastructure")
        raw_data = {
            "name": name,
            "url": entry.get("url"),
            "faucet_url": entry.get("faucet_url"),
            "sector": sector,
            "stage": entry.get("stage", "testnet"),
            "description": entry.get("description", ""),
            "has_testnet": bool(entry.get("has_testnet", True)),
            "has_points_program": bool(entry.get("has_points_program", False)),
            # 缺省按已发币处理：未写明的条目不能被假定为 pre-TGE
            "no_token_yet": bool(entry.get("no_token_yet", False)),
            "recent_funding": bool(entry.get("recent_funding", False)),
            "funding_total_usd": entry.get("funding_total_usd"),
            "funding_tier": entry.get("funding_tier"),
            "source": self.source_id,
        }

        signals = [
            RawSignal(
                signal_type="testnet_activity",
                signal_source=self.source_id,
                signal_data={
                    "stage": "testnet",
                    "faucet_url": entry.get("faucet_url"),
                    "curated": True,
                },
                signal_strength=0.85,
            )
        ]

        score = float(entry.get("discovery_score", 0.55))

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=f"curated-{name.lower()}",
            name=name,
            url=entry.get("url"),
            sector=sector,
            stage=raw_data["stage"],
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=score,
            discovered_at=datetime.now(UTC),
        )

    async def _fetch_remote_curated_lists(self) -> list[RawDiscovery]:
        """抓取开源社区维护的测试网列表 Markdown 并提取项目与水龙头信息。"""
        discoveries: list[RawDiscovery] = []
        headers = {
            "User-Agent": "AirdropAlphaAgent/2.0 (Web3 Research; Testnet Sync)",
            "Accept": "text/plain",
        }

        async with self.http_client(timeout=self.timeout) as client:
            for url in DEFAULT_REMOTE_CURATED_URLS:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        parsed = self._parse_markdown_table_or_links(resp.text)
                        discoveries.extend(parsed)
                except Exception as e:
                    self.logger.debug("github_curated.url_fetch_failed", url=url, error=str(e))
                    continue

        return discoveries

    def _parse_markdown_table_or_links(self, markdown_text: str) -> list[RawDiscovery]:
        """解析 Markdown 文档中出现的测试网与水龙头链接。

        识别典型格式：
        - [Network Name](https://...) - [Faucet](https://...)
        - | Network | Faucet Link |
        """
        results: list[RawDiscovery] = []
        lines = markdown_text.splitlines()

        # 匹配形如 [Name](url) 的 Markdown 链接
        link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^\)]+)\)")

        seen_names: set[str] = set()
        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#"):
                continue

            matches = link_pattern.findall(line_str)
            if not matches:
                continue

            # 取第一个链接作为项目名称或网络名称
            first_text, first_url = matches[0]
            name = first_text.strip()

            # 过滤通用无用词
            if name.lower() in ("faucet", "link", "here", "guide", "website", "explorer", "docs", "readme"):
                continue
            if len(name) < 2 or len(name) > 30:
                continue
            if name.lower() in seen_names:
                continue

            # 检查是否有显式水龙头链接
            faucet_url = None
            for txt, u in matches:
                if any(k in txt.lower() or k in u.lower() for k in ("faucet", "water", "claim", "testnet")):
                    faucet_url = u
                    break

            seen_names.add(name.lower())

            raw_data = {
                "name": name,
                "url": first_url,
                "faucet_url": faucet_url or first_url,
                "sector": "Infrastructure",
                "stage": "testnet",
                "description": f"Community-curated testnet faucet entry for {name}.",
                "has_testnet": True,
                "has_points_program": False,
                # 水龙头清单只说明「有测试网」，说明不了「没发币」。能给出的唯一
                # 反证是已发币品牌名单（Plume Network → plume）。
                "no_token_yet": not is_listed_brand_subproduct(name=name),
                "recent_funding": False,
                "source": self.source_id,
            }

            signals = [
                RawSignal(
                    signal_type="testnet_faucet",
                    signal_source=self.source_id,
                    signal_data={"faucet_url": faucet_url or first_url},
                    signal_strength=0.7,
                )
            ]

            results.append(
                RawDiscovery(
                    source_id=self.source_id,
                    raw_id=f"remote-testnet-{name.lower().replace(' ', '-')}",
                    name=name,
                    url=first_url,
                    sector="Infrastructure",
                    stage="testnet",
                    raw_data=raw_data,
                    raw_signals=signals,
                    discovery_score=0.48,
                    discovered_at=datetime.now(UTC),
                )
            )

        return results
