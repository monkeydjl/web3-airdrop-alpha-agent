"""DefiLlama Collector.

从 DefiLlama API 自动扫描有 TVL 但未发币的协议。
免费、无 Key，高价值空投候选源。

参考：
- DATA_SOURCE_STRATEGY.md §1. DefiLlama
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.noise import is_noise_protocol
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.utils.normalize import normalize_sector

logger = structlog.get_logger(__name__)


class DefiLlamaCollector(DataCollector):
    """DefiLlama 采集器。

    采集策略：
    1. 全量拉取 /protocols
    2. 过滤未发币协议（gecko_id 为空或 symbol 为空）
    3. 排除 CEX / 蓝筹子协议噪声
    4. TVL > $1M 进入候选池
    5. 根据 TVL、链数量、7日 TVL 变化、元信息完整度计算 discovery_score
    """

    MAX_ITEMS = 100  # 单次采集最多保留的项目数，避免写入过多

    TVL_THRESHOLD = 1_000_000  # TVL > $1M

    def __init__(self) -> None:
        super().__init__(source_id="defillama", source_name="DefiLlama")
        self.base_url = settings.defillama_base_url
        self.timeout = settings.defillama_timeout
        self.retry = settings.defillama_retry
        self.rate_limiter = TokenBucketRateLimiter("defillama")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return settings.defillama_enabled

    async def collect(self) -> CollectorResult:
        """执行 DefiLlama 全量协议采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            protocols = await self._fetch_protocols()
            self.logger.info(
                "defillama.fetched",
                total_protocols=len(protocols),
            )

            candidates = self._filter_candidates(protocols)
            # 限制数量并按 discovery_score 排序，保留质量最高的项目
            candidates = sorted(
                candidates,
                key=self._calculate_discovery_score,
                reverse=True,
            )[: self.MAX_ITEMS]
            self.logger.info(
                "defillama.candidates",
                count=len(candidates),
            )

            for protocol in candidates:
                discovery = self._build_discovery(protocol)
                result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("defillama.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_protocols(self) -> list[dict[str, Any]]:
        """拉取 DefiLlama /protocols 全量协议列表。"""
        url = f"{self.base_url}/protocols"

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list):
            raise ValueError(f"Unexpected DefiLlama response type: {type(data)}")

        return data

    def _filter_candidates(self, protocols: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """过滤出高价值未发币协议（排除 CEX/蓝筹噪声）。"""
        candidates = []
        skipped_noise = 0
        for protocol in protocols:
            if not self._is_unlisted(protocol):
                continue

            tvl = protocol.get("tvl") or 0
            if not isinstance(tvl, (int, float)) or tvl < self.TVL_THRESHOLD:
                continue

            if is_noise_protocol(protocol):
                skipped_noise += 1
                continue

            candidates.append(protocol)

        if skipped_noise:
            self.logger.info("defillama.noise_skipped", count=skipped_noise)
        return candidates

    def _is_noise_protocol(self, protocol: dict[str, Any]) -> bool:
        """Back-compat wrapper for tests."""
        return is_noise_protocol(protocol)

    def _is_unlisted(self, protocol: dict[str, Any]) -> bool:
        """判断协议是否未发币。

        DefiLlama 中很多未发币项目已注册 symbol 但尚未在 CoinGecko 上市，
        因此以 gecko_id 缺失作为主要判断；symbol 单独存在不足以证明已发币。
        """
        if protocol.get("has_token") is True:
            return False
        if protocol.get("has_token") is False:
            return True

        gecko_id = protocol.get("gecko_id")
        return not gecko_id

    def _build_discovery(self, protocol: dict[str, Any]) -> RawDiscovery:
        """将 DefiLlama 协议转换为 RawDiscovery。"""
        name = protocol.get("name", "")
        slug = protocol.get("slug", "")
        url = protocol.get("url") or f"https://defillama.com/protocol/{slug}"
        sector = normalize_sector(protocol.get("category", "DeFi"))
        stage = self._infer_stage(protocol)

        tvl = protocol.get("tvl") or 0
        change_7d = protocol.get("change_7d") or 0
        chains = protocol.get("chains", [])
        chain_count = len(chains) if isinstance(chains, list) else 0

        discovery_score = self._calculate_discovery_score(protocol)

        # Scoring pipeline reads these flags from raw_data (see CollectorAgent)
        no_token = self._is_unlisted(protocol)
        has_testnet = stage == "testnet" or bool(protocol.get("has_testnet"))
        raw_data = {
            "name": name,
            "url": url,
            "sector": sector,
            "stage": stage,
            "slug": slug,
            "tvl": tvl,
            "change_7d": change_7d,
            "chains": chains,
            "category": protocol.get("category"),
            "gecko_id": protocol.get("gecko_id"),
            "symbol": protocol.get("symbol"),
            "twitter": protocol.get("twitter"),
            "github": protocol.get("github"),
            "no_token_yet": no_token,
            "has_testnet": has_testnet,
            "has_points_program": False,
            "recent_funding": False,
        }

        signals = [
            RawSignal(
                signal_type="tvl",
                signal_source=self.source_id,
                signal_data={"tvl": tvl, "change_7d": change_7d},
                signal_strength=min(1.0, tvl / 10_000_000),  # 10M 为满分
            ),
            RawSignal(
                signal_type="chain_activity",
                signal_source=self.source_id,
                signal_data={"chain_count": chain_count, "chains": chains},
                signal_strength=min(1.0, chain_count / 5.0),
            ),
            RawSignal(
                signal_type="airdrop_hint",
                signal_source=self.source_id,
                signal_data={"no_token_yet": no_token, "has_testnet": has_testnet},
                signal_strength=0.8 if no_token else 0.2,
            ),
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=slug or name.lower().replace(" ", "-"),
            name=name,
            url=url,
            sector=sector,
            stage=stage,
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _infer_stage(self, protocol: dict[str, Any]) -> str:
        """从 DefiLlama 数据推断项目阶段。"""
        tvl = protocol.get("tvl") or 0
        if tvl > 100_000_000:
            return "mainnet"
        if tvl > 10_000_000:
            return "testnet"
        return "ideation"

    def _calculate_discovery_score(self, protocol: dict[str, Any]) -> float:
        """计算发现质量分 0-1。

        评分维度：
        - TVL 规模（40%）
        - 7日 TVL 增长趋势（20%）
        - 多链部署（15%）
        - 元信息完整度（15%）
        - 社交媒体/代码链接存在（10%）
        """
        tvl = protocol.get("tvl") or 0
        change_7d = protocol.get("change_7d") or 0
        chains = protocol.get("chains", [])
        chain_count = len(chains) if isinstance(chains, list) else 0

        # TVL 分数（10M 满分）
        tvl_score = min(1.0, tvl / 10_000_000)

        # 7日趋势分数（增长 50% 满分）
        trend_score = 0.0
        if change_7d > 0:
            trend_score = min(1.0, change_7d / 0.5)

        # 多链分数
        chain_score = min(1.0, chain_count / 5.0)

        # 元信息完整度
        meta_fields = [protocol.get("url"), protocol.get("twitter"), protocol.get("github")]
        meta_score = sum(1 for f in meta_fields if f) / len(meta_fields)

        # 社交/代码存在
        social_score = 0.0
        if protocol.get("twitter"):
            social_score += 0.5
        if protocol.get("github"):
            social_score += 0.5

        score = tvl_score * 0.40 + trend_score * 0.20 + chain_score * 0.15 + meta_score * 0.15 + social_score * 0.10

        return round(score, 4)

    async def health_check(self) -> dict[str, Any]:
        """检查 DefiLlama API 可用性。"""
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/protocols")
                response.raise_for_status()
                return {
                    "source_id": self.source_id,
                    "status": "healthy",
                    "protocols_count": len(response.json()) if isinstance(response.json(), list) else 0,
                }
        except Exception as e:
            return {
                "source_id": self.source_id,
                "status": "unhealthy",
                "error": str(e),
            }


if __name__ == "__main__":
    import asyncio

    async def main():
        collector = DefiLlamaCollector()
        if not collector.is_enabled():
            print("DefiLlama collector disabled in settings")
            return

        result = await collector.collect()
        print(f"Status: {result.status}")
        print(f"Items collected: {len(result.items)}")
        for item in result.items[:5]:
            print(f"  - {item.name} ({item.sector}) score={item.discovery_score}")

    asyncio.run(main())
