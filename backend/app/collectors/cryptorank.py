"""CryptoRank Collector.

Pulls currency market metadata from CryptoRank API for sector labels,
listing verification, and mid-cap heat signals.

Auth: query param `api_key` (verified against api.cryptorank.io/v1).

Reference:
- DATA_SOURCE_STRATEGY.md (CryptoRank)
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


class CryptoRankCollector(DataCollector):
    """CryptoRank 市场/赛道采集器。

    策略：
    1. 分页拉取 /currencies（需 API key）
    2. 提取 name/symbol/category/rank/市值与涨跌
    3. 已上市资产作为验证+赛道信号；中小市值且 7 日动量较高者给略高 discovery_score
    """

    PAGE_SIZE = 100
    MAX_ITEMS = 200
    # skip absolute mega-caps (noise for airdrop discovery)
    MIN_RANK = 50
    MAX_RANK = 800
    # Listed tokens are verification/heat signals — keep below analysis threshold 0.3
    MAX_DISCOVERY_SCORE = 0.28

    def __init__(self) -> None:
        super().__init__(source_id="cryptorank", source_name="CryptoRank")
        self.base_url = settings.cryptorank_base_url.rstrip("/")
        self.timeout = getattr(settings, "cryptorank_timeout", 30)
        self.api_key = settings.cryptorank_api_key
        self.rate_limiter = TokenBucketRateLimiter("cryptorank")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.cryptorank_enabled and self.api_key)

    async def collect(self) -> CollectorResult:
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            currencies = await self._fetch_currencies()
            self.logger.info("cryptorank.fetched", total=len(currencies))

            candidates: list[RawDiscovery] = []
            for item in currencies:
                discovery = self._build_discovery(item)
                if discovery is None:
                    continue
                candidates.append(discovery)

            candidates.sort(key=lambda d: d.discovery_score, reverse=True)
            result.items = candidates[: self.MAX_ITEMS]
            result.status = "success" if result.items else "partial"

        except Exception as e:
            self.logger.error("cryptorank.error", error=str(e))
            result.status = "error"
            result.error_message = str(e)
        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def _fetch_currencies(self) -> list[dict[str, Any]]:
        """Paginate /currencies until MAX_ITEMS * 2 raw rows or empty page."""
        url = f"{self.base_url}/currencies"
        headers = {"Accept": "application/json"}
        collected: list[dict[str, Any]] = []
        offset = 0
        target = self.MAX_ITEMS * 2

        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            while len(collected) < target:
                params = {
                    "api_key": self.api_key,
                    "limit": self.PAGE_SIZE,
                    "offset": offset,
                }
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError(f"Unexpected CryptoRank response type: {type(payload)}")
                page = payload.get("data") or []
                if not isinstance(page, list) or not page:
                    break
                collected.extend(page)
                offset += len(page)
                if len(page) < self.PAGE_SIZE:
                    break

        return collected

    def _build_discovery(self, item: dict[str, Any]) -> RawDiscovery | None:
        name = (item.get("name") or "").strip()
        if not name:
            return None

        rank = item.get("rank") or 0
        try:
            rank_i = int(rank)
        except (TypeError, ValueError):
            rank_i = 0
        if rank_i and (rank_i < self.MIN_RANK or rank_i > self.MAX_RANK):
            return None

        symbol = item.get("symbol") or ""
        slug = item.get("slug") or str(item.get("id") or symbol or name)
        category = item.get("category") or "DeFi"
        cat_l = str(category).lower()
        # Currency / pure meme mega brands add little airdrop alpha
        if cat_l in {"currency", "stablecoin", "meme"}:
            return None
        sector = normalize_sector(str(category))

        usd = {}
        values = item.get("values") or {}
        if isinstance(values, dict):
            usd = values.get("USD") or values.get("usd") or {}
        if not isinstance(usd, dict):
            usd = {}

        market_cap = usd.get("marketCap") or 0
        volume_24h = usd.get("volume24h") or item.get("volume24hBase") or 0
        price = usd.get("price") or 0
        change_24h = usd.get("percentChange24h") or 0
        change_7d = usd.get("percentChange7d") or 0
        # Prefer some momentum or mid-tier rank; drop dead flat mega-volume names
        try:
            ch7 = float(change_7d or 0)
            vol = float(volume_24h or 0)
        except (TypeError, ValueError):
            ch7, vol = 0.0, 0.0
        if ch7 <= 0 and not (80 <= rank_i <= 500):
            return None
        if vol > 5e8:  # extreme volume = already liquid blue chip
            return None

        raw_data = {
            "cryptorank_id": item.get("id"),
            "slug": slug,
            "symbol": symbol,
            "category": category,
            "type": item.get("type"),
            "rank": rank_i,
            "market_cap": market_cap,
            "volume_24h": volume_24h,
            "price": price,
            "percent_change_24h": change_24h,
            "percent_change_7d": change_7d,
            "circulating_supply": item.get("circulatingSupply"),
            "total_supply": item.get("totalSupply"),
            "last_updated": item.get("lastUpdated"),
        }

        discovery_score = self._calculate_discovery_score(
            rank=rank_i,
            change_7d=float(change_7d or 0),
            volume_24h=float(volume_24h or 0),
            market_cap=float(market_cap or 0),
        )

        signals = [
            RawSignal(
                signal_type="token_listed",
                signal_source=self.source_id,
                signal_data={
                    "symbol": symbol,
                    "rank": rank_i,
                    "market_cap": market_cap,
                    "category": category,
                },
                signal_strength=self._rank_strength(rank_i),
            ),
            RawSignal(
                signal_type="market_momentum",
                signal_source=self.source_id,
                signal_data={
                    "percent_change_7d": change_7d,
                    "percent_change_24h": change_24h,
                    "volume_24h": volume_24h,
                },
                signal_strength=min(1.0, max(0.0, abs(float(change_7d or 0)) / 50.0)),
            ),
        ]

        url = f"https://cryptorank.io/price/{slug}" if slug else None

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=str(slug),
            name=name,
            url=url,
            sector=sector,
            stage="mainnet",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _rank_strength(self, rank: int) -> float:
        if rank <= 0:
            return 0.4
        if rank <= 50:
            return 1.0
        if rank <= 200:
            return 0.7
        if rank <= 500:
            return 0.5
        return 0.3

    def _calculate_discovery_score(
        self,
        *,
        rank: int,
        change_7d: float,
        volume_24h: float,
        market_cap: float,
    ) -> float:
        """Listed assets stay below analysis threshold; heat signals only."""
        del market_cap  # Reserved for future scoring without changing the call contract.
        base = 0.08
        if 80 <= rank <= 400:
            rank_bonus = 0.08
        elif 400 < rank <= 800:
            rank_bonus = 0.05
        else:
            rank_bonus = 0.02

        mom = min(0.08, change_7d / 50.0 * 0.08) if change_7d > 0 else 0.0
        vol_score = 0.04 if volume_24h >= 1_000_000 else (0.02 if volume_24h >= 100_000 else 0.0)

        score = base + rank_bonus + mom + vol_score
        return round(min(self.MAX_DISCOVERY_SCORE, max(0.05, score)), 4)

    async def health_check(self) -> dict[str, Any]:
        try:
            async with self.rate_limiter, httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{self.base_url}/currencies",
                    params={"api_key": self.api_key, "limit": 1, "offset": 0},
                )
                response.raise_for_status()
                data = response.json()
                count = len(data.get("data") or []) if isinstance(data, dict) else 0
                return {
                    "source_id": self.source_id,
                    "status": "healthy",
                    "sample_count": count,
                }
        except Exception as e:
            return {
                "source_id": self.source_id,
                "status": "unhealthy",
                "error": str(e),
            }
