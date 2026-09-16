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


class TestDefiLlamaFacetFiltering:
    """2026-09 修复：已发币品牌的 symbol='-' 子条目不得混入 pre-TGE 候选。

    生产库实测泄漏样例："Zircuit Staking"（母条目 Zircuit 带 ZRC/gecko_id，
    在 _is_unlisted 处被过滤；子条目 symbol='-' 反而留下）。
    """

    def test_brand_prefix_facet_of_listed_protocol_skipped(self, collector: DefiLlamaCollector) -> None:
        protocols = [
            sample_protocol(
                name="Zircuit", slug="zircuit", category="Canonical Bridge",
                symbol="ZRC", gecko_id="zircuit",
            ),
            sample_protocol(name="Zircuit Staking", slug="zircuit-staking", category="Farm"),
        ]
        candidates = collector._filter_candidates(protocols)
        assert [c["name"] for c in candidates] == []

    def test_parent_linked_facet_of_listed_protocol_skipped(self, collector: DefiLlamaCollector) -> None:
        protocols = [
            sample_protocol(
                name="Solv Protocol", slug="solv-protocol", category="Yield",
                symbol="SOLV", gecko_id="solv-protocol",
            ),
            {
                **sample_protocol(name="Solv Staking", slug="solv-staking", category="Farm"),
                "parentProtocol": "parent#solv-protocol",
            },
        ]
        candidates = collector._filter_candidates(protocols)
        assert [c["name"] for c in candidates] == []

    def test_facet_of_unlisted_parent_kept(self, collector: DefiLlamaCollector) -> None:
        """母项目同样未上市 → 子条目跟随母项目保留（母条目承载 alpha）。"""
        protocols = [
            sample_protocol(name="Tonstack", slug="tonstack", category="Liquid Staking"),
            {
                **sample_protocol(name="Tonstack LSD", slug="tonstack-lsd", category="Liquid Staking"),
                "parentProtocol": "parent#tonstack",
            },
        ]
        candidates = collector._filter_candidates(protocols)
        assert {c["name"] for c in candidates} == {"Tonstack", "Tonstack LSD"}

    def test_short_listed_brand_stems_do_not_clobber(self, collector: DefiLlamaCollector) -> None:
        """≥3 字符门槛：两字符上市条目名（如 "SX"）不作为品牌前缀判据。"""
        protocols = [
            sample_protocol(name="SX", slug="sx", category="Prediction Market",
                            symbol="SX", gecko_id="sx"),
            sample_protocol(name="SXPB Vault", slug="sxpb-vault", category="Yield"),
        ]
        candidates = collector._filter_candidates(protocols)
        assert [c["name"] for c in candidates] == ["SXPB Vault"]


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


class TestFacetOfListedBrandToken:
    """品牌首词兜底：parentProtocol 为 null、名字与母条目互不为前缀的
    已发币品牌子条目，必须被排除出候选。

    实测语料（2026-09-06）：Plume Vaults（symbol='-'、parentProtocol=null、
    TVL $144M）与母条目 Plume Mainnet（symbol='PLUME'）—— 既有前缀规则
    ("Zircuit Staking" ⊂ "Zircuit") 接不住这对，Plume Vaults 以 WATCH 65
    混进扫描结果。
    """

    def test_plume_vaults_excluded_as_brand_facet(self, collector: DefiLlamaCollector) -> None:
        protocols = [
            sample_protocol(name="Plume Mainnet", slug="plume-mainnet", symbol="PLUME", gecko_id="plume", tvl=0),
            sample_protocol(name="Plume Vaults", slug="plume-vaults", tvl=144_705_790),
        ]
        assert collector._filter_candidates(protocols) == []

    def test_genuine_unlisted_project_with_similar_name_kept(self, collector: DefiLlamaCollector) -> None:
        """品牌词只按首词匹配：Mystic Finance myPLUME 的品牌是 Mystic，
        不能因为名字里带 plume 被误杀。"""
        protocols = [
            sample_protocol(name="Plume Mainnet", slug="plume-mainnet", symbol="PLUME", gecko_id="plume", tvl=0),
            sample_protocol(
                name="Mystic Finance myPLUME", slug="mystic-finance-myplume", symbol="-", tvl=200_000_000
            ),
        ]
        candidates = collector._filter_candidates(protocols)
        assert [c["name"] for c in candidates] == ["Mystic Finance myPLUME"]


class TestZombieFilter:
    """入库前的死项目过滤：没官网、GitHub 久不更新，不该出现在候选里。

    导火索（2026-09-15 用户原话）：「像 Goose 那样的项目根本就不该进这个库」 —
    这类项目数据面再健康（TVL 在动）也查不到别的证据：
    - 官网缺失（或者 defillama.com 占位链接）；
    - GitHub 注册后没人每年再 push 过；
    - 跟持有类项目的「死网站」是可以由它独立查证的。
    """

    def test_url_missing_and_github_stale_is_dropped(self, collector: DefiLlamaCollector) -> None:
        """F1：url 缺失且无 ppmitted github。**假定应采取尽的快筛。"""
        protocols = [
            {"name": "DeadZone", "slug": "deadzone", "url": "", "github": ["deadgh"],
             "category": "DeFi", "tvl": 5_000_000, "twitter": None, "symbol": "-"},
            {"name": "LiveLink", "slug": "livelink", "url": "https://live.example",
             "github": ["lslabs"], "category": "DeFi", "tvl": 20_000_000, "symbol": "-"},
        ]
        out = collector._filter_candidates(protocols)
        names = [p["name"] for p in out]
        assert "DeadZone" not in names
        assert "LiveLink" in names

    def test_url_placeholder_never_survives(self, collector: DefiLlamaCollector) -> None:
        """F2：URL 里挂着聚合站详情页占位链（非真官网）的也应被撇。"""
        protocols = [
            {"name": "Placeholder", "slug": "ph", "url": "https://defillama.com/protocol/ph",
             "category": "DeFi", "tvl": 5_000_000, "symbol": "-"},
            {"name": "RealSite", "slug": "real", "url": "https://real.example",
             "category": "DeFi", "tvl": 5_000_000, "symbol": "-"},
        ]
        out = collector._filter_candidates(protocols)
        names = [p["name"] for p in out]
        assert "Placeholder" not in names
        assert "RealSite" in names

    def test_zombie_with_testnet_kept(self, collector: DefiLlamaCollector) -> None:
        """Goose 那反证：就算项目有 testnet 也不该进（因为这是个噪音特质）。"""
        protocols = [
            {"name": "Goose", "slug": "goose", "url": "",
             "github": ["GooseFarmLabs"], "has_testnet": True,
             "category": "DeFi", "tvl": 5_000_000, "symbol": "-"},
        ]
        out = collector._filter_candidates(protocols)
        assert out == [], "Goose 这种条目不该留下来 (testnet 是展能不是保命)"
