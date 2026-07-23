"""CoinGecko Collector.

拉取 CoinGecko 市场数据，用于验证项目代币是否已上市。
返回低 discovery_score 的 RawDiscovery（作为验证信号，不进入分析 pipeline）。

参考：
- DATA_SOURCE_STRATEGY.md §3. CoinGecko
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.utils.normalize import normalize_sector

logger = structlog.get_logger(__name__)


class CoinGeckoCollector(DataCollector):
    """CoinGecko 采集器。

    采集策略：
    1. 拉取 /coins/markets 前 250 市值代币
    2. 提取 symbol、name、market_cap、price、24h 变化
    3. 作为"已发币验证信号"写入 project_signals

    注意：CoinGecko Demo API 限流约 30 calls/min，建议配置 COINGECKO_API_KEY
    以提升配额和稳定性。
    """

    TOP_N = 250
    VS_CURRENCY = "usd"

    def __init__(self) -> None:
        super().__init__(source_id="coingecko", source_name="CoinGecko")
        self.base_url = settings.coingecko_api_base_url
        self.timeout = settings.coingecko_timeout
        self.retry = settings.coingecko_retry
        self.rate_limiter = TokenBucketRateLimiter("coingecko")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return settings.coingecko_enabled

    async def collect(self) -> CollectorResult:
        """执行 CoinGecko 市场数据采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            coins = await self._fetch_markets()
            self.logger.info(
                "coingecko.fetched",
                total_coins=len(coins),
            )

            for coin in coins:
                discovery = self._build_discovery(coin)
                result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("coingecko.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_markets(self) -> list[dict[str, Any]]:
        """拉取 CoinGecko 市场数据。"""
        url = f"{self.base_url}/coins/markets"
        params = {
            "vs_currency": self.VS_CURRENCY,
            "order": "market_cap_desc",
            "per_page": self.TOP_N,
            "page": 1,
            "sparkline": "false",
        }
        headers: dict[str, str] = {}
        if settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = settings.coingecko_api_key

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            data = response.json()

        if not isinstance(data, list):
            raise ValueError(f"Unexpected CoinGecko response type: {type(data)}")

        return data

    def _build_discovery(self, coin: dict[str, Any]) -> RawDiscovery:
        """把 CoinGecko 币种转换为 RawDiscovery（验证信号）。"""
        name = coin.get("name", "")
        symbol = coin.get("symbol", "")
        coin_id = coin.get("id", "")

        # 使用 symbol 作为项目名，因为 raw_projects 通常也用 symbol/name
        display_name = name or symbol or coin_id

        url = coin.get("image")  # 无官网，用图标占位

        # Economic raw: preserve provider None; never coerce missing → 0.
        market_cap_raw = coin.get("market_cap")
        current_price_raw = coin.get("current_price")
        price_change_percentage_24h_raw = coin.get("price_change_percentage_24h")
        total_volume_raw = coin.get("total_volume")
        circulating_supply_raw = coin.get("circulating_supply")
        market_cap_rank_raw = coin.get("market_cap_rank")

        # Legacy locals for signal strength / signal_data — missing → 0.
        market_cap = market_cap_raw if market_cap_raw is not None else 0
        current_price = current_price_raw if current_price_raw is not None else 0
        market_cap_rank = market_cap_rank_raw if market_cap_rank_raw is not None else 0
        # Non-economic field shape unchanged.
        price_change_24h = coin.get("price_change_24h") or 0

        raw_data = {
            "coin_id": coin_id,
            "symbol": symbol,
            "market_cap": market_cap_raw,
            "current_price": current_price_raw,
            "price_change_24h": price_change_24h,
            "price_change_percentage_24h": price_change_percentage_24h_raw,
            "total_volume": total_volume_raw,
            "circulating_supply": circulating_supply_raw,
            "market_cap_rank": market_cap_rank_raw,
            "last_updated": coin.get("last_updated"),
        }

        signals = [
            RawSignal(
                signal_type="token_listed",
                signal_source="coingecko",
                signal_data={
                    "symbol": symbol,
                    "market_cap": market_cap,
                    "current_price": current_price,
                    "market_cap_rank": market_cap_rank,
                },
                signal_strength=self._calculate_signal_strength(market_cap_rank),
            ),
        ]

        # 已上市代币 discovery_score 低，作为验证信号而非新发现
        discovery_score = 0.1

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=coin_id,
            name=display_name,
            url=url,
            sector=normalize_sector("DeFi"),  # CoinGecko 币种不细分赛道，默认 DeFi
            stage="mainnet",  # 已上市视为 mainnet
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _calculate_signal_strength(self, market_cap_rank: int) -> float:
        """根据市值排名计算信号强度。"""
        if market_cap_rank <= 0:
            return 0.5
        if market_cap_rank <= 10:
            return 1.0
        if market_cap_rank <= 100:
            return 0.8
        if market_cap_rank <= 250:
            return 0.6
        return 0.4

    async def health_check(self) -> dict[str, Any]:
        """检查 CoinGecko API 可用性。"""
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                headers: dict[str, str] = {}
                if settings.coingecko_api_key:
                    headers["x-cg-demo-api-key"] = settings.coingecko_api_key
                response = await client.get(
                    f"{self.base_url}/ping",
                    headers=headers,
                )
                response.raise_for_status()
                return {
                    "source_id": self.source_id,
                    "status": "healthy",
                    "ping": response.json(),
                }
        except Exception as e:
            return {
                "source_id": self.source_id,
                "status": "unhealthy",
                "error": str(e),
            }
