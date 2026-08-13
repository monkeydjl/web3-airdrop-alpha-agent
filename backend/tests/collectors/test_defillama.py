"""Tests for DefiLlama Collector."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.collectors.defillama import DefiLlamaCollector


@pytest.fixture
def collector() -> DefiLlamaCollector:
    return DefiLlamaCollector()


def sample_protocol(
    name: str = "Alpha Protocol",
    slug: str = "alpha-protocol",
    tvl: float = 5_000_000,
    change_7d: float = 0.25,
    category: str = "Lending",
    gecko_id: str | None = None,
    symbol: str | None = None,
    url: str = "https://alpha.example.com",
    twitter: str = "@alpha",
    github: str = "alpha/repo",
    chains: list[str] | None = None,
) -> dict:
    return {
        "name": name,
        "slug": slug,
        "tvl": tvl,
        "change_7d": change_7d,
        "category": category,
        "gecko_id": gecko_id,
        "symbol": symbol,
        "url": url,
        "twitter": twitter,
        "github": github,
        "chains": chains or ["Ethereum", "Arbitrum"],
    }


class TestDefiLlamaFilterCandidates:
    def test_includes_unlisted_high_tvl_protocol(self, collector: DefiLlamaCollector) -> None:
        protocols = [sample_protocol()]
        candidates = collector._filter_candidates(protocols)
        assert len(candidates) == 1
        assert candidates[0]["name"] == "Alpha Protocol"

    def test_excludes_listed_protocol(self, collector: DefiLlamaCollector) -> None:
        protocols = [sample_protocol(gecko_id="alpha", symbol="ALPHA")]
        candidates = collector._filter_candidates(protocols)
        assert len(candidates) == 0

    def test_excludes_low_tvl_protocol(self, collector: DefiLlamaCollector) -> None:
        protocols = [sample_protocol(tvl=100_000)]
        candidates = collector._filter_candidates(protocols)
        assert len(candidates) == 0

    def test_has_token_false_triggers_include(self, collector: DefiLlamaCollector) -> None:
        protocols = [{**sample_protocol(), "has_token": False}]
        candidates = collector._filter_candidates(protocols)
        assert len(candidates) == 1

    def test_excludes_cex_category(self, collector: DefiLlamaCollector) -> None:
        protocols = [sample_protocol(name="BingX", slug="bingx", category="CEX")]
        assert collector._filter_candidates(protocols) == []

    def test_excludes_known_brand_child(self, collector: DefiLlamaCollector) -> None:
        protocols = [
            sample_protocol(name="Uniswap V4", slug="uniswap-v4", category="Dexs"),
            sample_protocol(name="Aave V3", slug="aave-v3", category="Lending"),
            sample_protocol(name="Coinbase Bridge", slug="coinbase-bridge", category="Bridge"),
        ]
        assert collector._filter_candidates(protocols) == []

    def test_keeps_unknown_unlisted_defi(self, collector: DefiLlamaCollector) -> None:
        protocols = [sample_protocol(name="Nova Vault", slug="nova-vault", category="Yield")]
        candidates = collector._filter_candidates(protocols)
        assert len(candidates) == 1


class TestDefiLlamaDiscoveryScore:
    def test_score_components(self, collector: DefiLlamaCollector) -> None:
        protocol = sample_protocol(tvl=10_000_000, change_7d=0.5, chains=["A", "B", "C", "D", "E"])
        score = collector._calculate_discovery_score(protocol)
        assert 0.0 <= score <= 1.0
        assert score >= 0.5  # 高分协议应明显超过阈值

    def test_low_score_for_minimal_protocol(self, collector: DefiLlamaCollector) -> None:
        protocol = sample_protocol(
            tvl=1_000_000,
            change_7d=-0.1,
            chains=["Ethereum"],
            url=None,
            twitter=None,
            github=None,
        )
        score = collector._calculate_discovery_score(protocol)
        assert 0.0 <= score < 0.4


@pytest.mark.asyncio
class TestDefiLlamaCollect:
    @respx.mock
    async def test_collect_returns_candidates(self, collector: DefiLlamaCollector) -> None:
        protocols = [
            sample_protocol(name="Alpha", slug="alpha"),
            sample_protocol(name="Beta", slug="beta", tvl=100_000),  # 低 TVL 被过滤
            sample_protocol(name="Gamma", slug="gamma", gecko_id="gamma"),  # 已发币被过滤
        ]
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=protocols))

        result = await collector.collect()

        assert result.status == "success"
        assert len(result.items) == 1
        assert result.items[0].name == "Alpha"
        assert result.items[0].discovery_score >= 0.3

    @respx.mock
    async def test_collect_handles_api_error(self, collector: DefiLlamaCollector) -> None:
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(500, text="Internal Error"))

        result = await collector.collect()

        assert result.status == "error"
        assert result.error_message is not None


@pytest.mark.asyncio
class TestDefiLlamaHealthCheck:
    @respx.mock
    async def test_health_check_healthy(self, collector: DefiLlamaCollector) -> None:
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(200, json=[{"name": "x"}]))

        health = await collector.health_check()

        assert health["status"] == "healthy"
        assert health["protocols_count"] == 1

    @respx.mock
    async def test_health_check_unhealthy(self, collector: DefiLlamaCollector) -> None:
        respx.get("https://api.llama.fi/protocols").mock(return_value=Response(500))

        health = await collector.health_check()

        assert health["status"] == "unhealthy"


class TestDefiLlamaEconomicOptionA:
    """Option A: preserve provider None in economic raw_data; legacy scores use local 0."""

    def test_missing_economic_fields_are_none_not_zero(self, collector: DefiLlamaCollector) -> None:
        protocol = {
            "name": "Sparse Protocol",
            "slug": "sparse-protocol",
            "category": "Lending",
            "gecko_id": None,
            "symbol": None,
            "url": "https://sparse.example.com",
            "twitter": "@sparse",
            "github": "sparse/repo",
            # tvl/change_7d/chains intentionally absent
        }
        # Filter needs tvl for inclusion; build_discovery is tested directly for raw shape
        discovery = collector._build_discovery({**protocol, "tvl": 5_000_000})
        raw = discovery.raw_data
        assert raw.get("change_7d") is None or "change_7d" not in raw
        assert raw.get("change_7d") != 0
        assert raw["change_7d_unit"] == "ratio"
        # tvl present as real value
        assert raw["tvl"] == 5_000_000

        # Explicit provider nulls
        discovery_null = collector._build_discovery(
            {
                **protocol,
                "tvl": None,
                "change_7d": None,
                "chains": None,
            }
        )
        raw_null = discovery_null.raw_data
        assert raw_null["tvl"] is None
        assert raw_null["change_7d"] is None
        assert raw_null["chains"] is None
        assert raw_null["change_7d_unit"] == "ratio"

    def test_real_zero_preserved_in_raw_data(self, collector: DefiLlamaCollector) -> None:
        protocol = sample_protocol(tvl=0, change_7d=0.0)
        discovery = collector._build_discovery(protocol)
        assert discovery.raw_data["tvl"] == 0
        assert discovery.raw_data["change_7d"] == 0.0
        assert discovery.raw_data["change_7d_unit"] == "ratio"

    def test_always_writes_change_7d_unit_ratio(self, collector: DefiLlamaCollector) -> None:
        for change in (0.25, 0, None):
            protocol = (
                sample_protocol(change_7d=change)
                if change is not None
                else {
                    **sample_protocol(),
                    "change_7d": None,
                }
            )
            discovery = collector._build_discovery(protocol)
            assert discovery.raw_data["change_7d_unit"] == "ratio"

    def test_legacy_score_and_signal_unchanged_for_present_values(self, collector: DefiLlamaCollector) -> None:
        protocol = sample_protocol(tvl=10_000_000, change_7d=0.5, chains=["A", "B", "C", "D", "E"])
        discovery = collector._build_discovery(protocol)
        # Pre-Option-A score formula on same inputs
        expected_score = collector._calculate_discovery_score(protocol)
        assert discovery.discovery_score == expected_score
        tvl_signal = next(s for s in discovery.raw_signals if s.signal_type == "tvl")
        assert tvl_signal.signal_strength == min(1.0, 10_000_000 / 10_000_000)
        assert tvl_signal.signal_data["tvl"] == 10_000_000
        assert tvl_signal.signal_data["change_7d"] == 0.5

    def test_legacy_score_uses_zero_fallback_when_change_missing(self, collector: DefiLlamaCollector) -> None:
        protocol = sample_protocol(tvl=5_000_000, change_7d=0.25)
        del protocol["change_7d"]
        score_missing = collector._calculate_discovery_score(protocol)
        score_zero = collector._calculate_discovery_score(sample_protocol(tvl=5_000_000, change_7d=0))
        assert score_missing == score_zero
        discovery = collector._build_discovery(protocol)
        assert discovery.discovery_score == score_missing
        # raw still None/missing, not coerced to 0
        assert discovery.raw_data.get("change_7d") is None or "change_7d" not in discovery.raw_data
