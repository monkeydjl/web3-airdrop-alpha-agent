"""Task 3: provider economic normalizers — registry, canonical payload, factor mapping."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.opportunity.economic_models import NormalizedFactor, NormalizedObservation, payload_sha256


def _utc(ts: str = "2026-07-22T12:00:00+00:00") -> datetime:
    return datetime.fromisoformat(ts).astimezone(UTC)


OBSERVED = _utc("2026-07-22T12:00:00+00:00")
EXPIRES = _utc("2026-07-23T12:00:00+00:00")


# ── Registry ────────────────────────────────────────────────────


def test_provider_raw_field_keys_exact_and_immutable():
    from app.opportunity.economic_normalizers import PROVIDER_RAW_FIELD_KEYS

    assert isinstance(PROVIDER_RAW_FIELD_KEYS, MappingProxyType)
    assert set(PROVIDER_RAW_FIELD_KEYS.keys()) == {"defillama", "coingecko", "cryptorank"}

    assert PROVIDER_RAW_FIELD_KEYS["defillama"] == frozenset(
        {"tvl", "change_7d", "change_7d_unit", "chains", "no_token_yet"}
    )
    assert PROVIDER_RAW_FIELD_KEYS["coingecko"] == frozenset(
        {
            "market_cap",
            "current_price",
            "total_volume",
            "circulating_supply",
            "market_cap_rank",
            "price_change_percentage_24h",
        }
    )
    assert PROVIDER_RAW_FIELD_KEYS["cryptorank"] == frozenset(
        {
            "market_cap",
            "price",
            "volume_24h",
            "circulating_supply",
            "total_supply",
            "rank",
            "percent_change_24h",
            "percent_change_7d",
        }
    )
    for key in PROVIDER_RAW_FIELD_KEYS:
        assert isinstance(PROVIDER_RAW_FIELD_KEYS[key], frozenset)

    with pytest.raises(TypeError):
        PROVIDER_RAW_FIELD_KEYS["extra"] = frozenset()  # type: ignore[index]
    with pytest.raises((TypeError, AttributeError)):
        PROVIDER_RAW_FIELD_KEYS["defillama"].add("hack")  # type: ignore[attr-defined]


def test_defillama_change_7d_unit_constant():
    from app.opportunity.economic_normalizers import DEFILLAMA_CHANGE_7D_PROVIDER_UNIT

    assert DEFILLAMA_CHANGE_7D_PROVIDER_UNIT == "ratio"


# ── Shared normalize_* helpers ──────────────────────────────────


def test_normalize_decimal_string_round_half_even_and_rejects():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        normalize_decimal_string,
    )

    # 1.234567895 → 1.23456790 (ROUND_HALF_EVEN on 5 when prior digit odd? 9 odd → up)
    # quantize to 8 places: 1.234567895 → look at 9th digit after quantize target
    assert normalize_decimal_string("1.234567895", nonnegative=True) == "1.23456790"
    assert normalize_decimal_string(0, nonnegative=True) == "0.00000000"
    assert normalize_decimal_string("2.5e-1", nonnegative=True) == "0.25000000"
    # no scientific notation in output
    assert "e" not in normalize_decimal_string("1e-8", nonnegative=True).lower()

    with pytest.raises(EconomicNormalizationError):
        normalize_decimal_string(True, nonnegative=True)
    with pytest.raises(EconomicNormalizationError):
        normalize_decimal_string("", nonnegative=True)
    with pytest.raises(EconomicNormalizationError):
        normalize_decimal_string(None, nonnegative=True)
    with pytest.raises(EconomicNormalizationError):
        normalize_decimal_string(float("nan"), nonnegative=True)
    with pytest.raises(EconomicNormalizationError):
        normalize_decimal_string(-1, nonnegative=True)
    # negative allowed when nonnegative=False
    assert normalize_decimal_string(-1.5, nonnegative=False) == "-1.50000000"


def test_normalize_ratio_string_with_divisor():
    from app.opportunity.economic_normalizers import normalize_ratio_string

    assert normalize_ratio_string(25, divisor=Decimal("100")) == "0.25000000"
    assert normalize_ratio_string(0.5, divisor=Decimal("1")) == "0.50000000"
    assert normalize_ratio_string(0, divisor=Decimal("100")) == "0.00000000"


def test_normalize_market_rank_strict():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        normalize_market_rank,
    )

    assert normalize_market_rank(1) == 1
    assert normalize_market_rank(0) == 0
    assert normalize_market_rank("12") == 12
    with pytest.raises(EconomicNormalizationError):
        normalize_market_rank(True)
    with pytest.raises(EconomicNormalizationError):
        normalize_market_rank(-1)
    with pytest.raises(EconomicNormalizationError):
        normalize_market_rank(1.5)
    with pytest.raises(EconomicNormalizationError):
        normalize_market_rank(None)


def test_normalize_chains_json_sorted_unique_nonempty():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        normalize_chains_json,
    )

    assert normalize_chains_json(["Arbitrum", "Ethereum"]) == ("Arbitrum", "Ethereum")
    assert normalize_chains_json(["Ethereum", "Arbitrum"]) == ("Arbitrum", "Ethereum")
    assert normalize_chains_json(["  eth  ", "arb"]) == ("arb", "eth")
    with pytest.raises(EconomicNormalizationError):
        normalize_chains_json([])
    with pytest.raises(EconomicNormalizationError):
        normalize_chains_json(["", "x"])
    with pytest.raises(EconomicNormalizationError):
        normalize_chains_json(["a", "a"])
    with pytest.raises(EconomicNormalizationError):
        normalize_chains_json("Ethereum")
    with pytest.raises(EconomicNormalizationError):
        normalize_chains_json(None)


def test_normalize_strict_bool():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        normalize_strict_bool,
    )

    assert normalize_strict_bool(True) is True
    assert normalize_strict_bool(False) is False
    with pytest.raises(EconomicNormalizationError):
        normalize_strict_bool(1)
    with pytest.raises(EconomicNormalizationError):
        normalize_strict_bool("true")


# ── sanitize_source_url ─────────────────────────────────────────


def test_sanitize_source_url_strips_query_fragment_rejects_bad():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        sanitize_source_url,
    )

    clean = sanitize_source_url(
        "https://api.example.com/v1/coin?api_key=SECRET&token=tok#frag"
    )
    assert clean == "https://api.example.com/v1/coin"
    assert "api_key" not in clean
    assert "token" not in clean
    assert "SECRET" not in clean
    assert "frag" not in clean
    assert "?" not in clean
    assert "#" not in clean

    assert sanitize_source_url("http://example.com/path") == "http://example.com/path"

    with pytest.raises(EconomicNormalizationError):
        sanitize_source_url("ftp://example.com/x")
    with pytest.raises(EconomicNormalizationError):
        sanitize_source_url("https://user:pass@example.com/x")
    with pytest.raises(EconomicNormalizationError):
        sanitize_source_url("not-a-url")


# ── canonical_provider_payload ──────────────────────────────────


def test_canonical_provider_payload_omit_none_keep_zero_whitelist():
    from app.opportunity.economic_normalizers import canonical_provider_payload

    payload = canonical_provider_payload(
        "coingecko",
        {
            "market_cap": 0,
            "current_price": None,
            "total_volume": 100,
            "noise_field": 999,
            "circulating_supply": 1,
            "market_cap_rank": 2,
            "price_change_percentage_24h": 0.5,
        },
    )
    assert payload == {
        "market_cap": 0,
        "total_volume": 100,
        "circulating_supply": 1,
        "market_cap_rank": 2,
        "price_change_percentage_24h": 0.5,
    }
    assert "current_price" not in payload
    assert "noise_field" not in payload
    # payload is the sole hash input
    digest = payload_sha256(payload)
    assert len(digest) == 64
    assert digest == payload_sha256(
        {
            "market_cap": 0,
            "total_volume": 100,
            "circulating_supply": 1,
            "market_cap_rank": 2,
            "price_change_percentage_24h": 0.5,
        }
    )


def test_canonical_defillama_requires_change_7d_unit_ratio():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        canonical_provider_payload,
    )

    ok = canonical_provider_payload(
        "defillama",
        {"tvl": 1_000_000, "change_7d": 0.1, "change_7d_unit": "ratio", "no_token_yet": True},
    )
    assert ok["change_7d_unit"] == "ratio"
    assert ok["tvl"] == 1_000_000

    with pytest.raises(EconomicNormalizationError):
        canonical_provider_payload("defillama", {"tvl": 1, "change_7d": 0.1})
    with pytest.raises(EconomicNormalizationError):
        canonical_provider_payload(
            "defillama", {"tvl": 1, "change_7d": 0.1, "change_7d_unit": None}
        )
    with pytest.raises(EconomicNormalizationError):
        canonical_provider_payload(
            "defillama", {"tvl": 1, "change_7d": 0.1, "change_7d_unit": "percent"}
        )


# ── normalize_provider_payload factor mapping ───────────────────


def test_normalize_defillama_full_row_sorted_factors_and_metadata():
    from app.opportunity.economic_normalizers import normalize_provider_payload

    factors = normalize_provider_payload(
        source_id="defillama",
        raw_data={
            "tvl": 5_000_000.123456789,
            "change_7d": 0.25,
            "change_7d_unit": "ratio",
            "chains": ["Ethereum", "Arbitrum"],
            "no_token_yet": True,
            "ignored": "x",
        },
        source_url="https://defillama.com/protocol/alpha?api_key=SECRET#frag",
        observed_at=OBSERVED,
        expires_at=EXPIRES,
    )
    assert isinstance(factors, tuple)
    assert all(isinstance(f, NormalizedFactor) for f in factors)
    keys = [f.factor_key for f in factors]
    assert keys == sorted(keys)
    assert keys == [
        "chains_json",
        "token_unlisted_proxy",
        "tvl_change_7d_ratio",
        "tvl_usd",
    ]

    by_key = {f.factor_key: f for f in factors}
    assert by_key["tvl_usd"].value == "5000000.12345679"
    assert by_key["tvl_usd"].value_type == "string"
    assert by_key["tvl_usd"].unit == "usd"
    assert by_key["tvl_change_7d_ratio"].value == "0.25000000"
    assert by_key["tvl_change_7d_ratio"].unit == "ratio"
    assert by_key["tvl_change_7d_ratio"].value_type == "string"
    assert by_key["chains_json"].value_type == "json"
    assert by_key["chains_json"].value == ("Arbitrum", "Ethereum")
    assert by_key["chains_json"].unit is None
    assert by_key["token_unlisted_proxy"].value is True
    assert by_key["token_unlisted_proxy"].value_type == "bool"
    assert by_key["token_unlisted_proxy"].unit is None

    for f in factors:
        assert f.source_type == "public_aggregator"
        assert f.independence_group == "defillama-protocols"
        assert f.source_grade == "C"
        assert f.verification_status == "verified"
        assert f.source_url == "https://defillama.com/protocol/alpha"
        assert "api_key" not in f.source_url
        assert f.observed_at == OBSERVED
        assert f.expires_at == EXPIRES
        # 11 fields
        assert set(NormalizedFactor.model_fields.keys()) == {
            "factor_key",
            "value",
            "value_type",
            "unit",
            "source_type",
            "source_grade",
            "verification_status",
            "independence_group",
            "source_url",
            "observed_at",
            "expires_at",
        }

    # Missing fields not filled
    sparse = normalize_provider_payload(
        source_id="defillama",
        raw_data={"tvl": 1.0, "change_7d_unit": "ratio"},
        source_url="https://defillama.com/p",
        observed_at=OBSERVED,
        expires_at=EXPIRES,
    )
    assert [f.factor_key for f in sparse] == ["tvl_usd"]


def test_normalize_coingecko_mapping_never_uses_price_change_24h():
    from app.opportunity.economic_normalizers import normalize_provider_payload

    factors = normalize_provider_payload(
        source_id="coingecko",
        raw_data={
            "market_cap": 1_000,
            "current_price": 2.5,
            "total_volume": 3,
            "circulating_supply": 4,
            "market_cap_rank": 10,
            "price_change_percentage_24h": 12.5,
            "price_change_24h": 999,  # must never map
        },
        source_url="https://api.coingecko.com/api/v3/coins/markets?x=1",
        observed_at=OBSERVED,
        expires_at=EXPIRES,
    )
    by_key = {f.factor_key: f for f in factors}
    assert set(by_key) == {
        "circulating_supply",
        "market_cap_usd",
        "market_rank",
        "price_change_24h_ratio",
        "price_usd",
        "volume_24h_usd",
    }
    assert by_key["price_change_24h_ratio"].value == "0.12500000"
    assert by_key["price_change_24h_ratio"].unit == "ratio"
    assert by_key["market_rank"].value == 10
    assert by_key["market_rank"].value_type == "number"
    assert by_key["market_rank"].unit is None
    assert by_key["circulating_supply"].unit is None
    assert by_key["market_cap_usd"].unit == "usd"
    for f in factors:
        assert f.source_type == "public_market_data"
        assert f.independence_group == "market-aggregators"
        assert f.source_url == "https://api.coingecko.com/api/v3/coins/markets"


def test_normalize_cryptorank_mapping():
    from app.opportunity.economic_normalizers import normalize_provider_payload

    factors = normalize_provider_payload(
        source_id="cryptorank",
        raw_data={
            "market_cap": 50_000_000,
            "price": 0.5,
            "volume_24h": 2_000_000,
            "circulating_supply": 1_000_000,
            "total_supply": 2_000_000,
            "rank": 120,
            "percent_change_24h": 5,
            "percent_change_7d": 25,
        },
        source_url="https://cryptorank.io/price/mid",
        observed_at=OBSERVED,
        expires_at=EXPIRES,
    )
    by_key = {f.factor_key: f for f in factors}
    assert by_key["market_cap_usd"].value == "50000000.00000000"
    assert by_key["price_usd"].value == "0.50000000"
    assert by_key["volume_24h_usd"].value == "2000000.00000000"
    assert by_key["circulating_supply"].value == "1000000.00000000"
    assert by_key["total_supply"].value == "2000000.00000000"
    assert by_key["market_rank"].value == 120
    assert by_key["price_change_24h_ratio"].value == "0.05000000"
    assert by_key["price_change_7d_ratio"].value == "0.25000000"
    assert [f.factor_key for f in factors] == sorted(by_key)
    for f in factors:
        assert f.source_type == "public_market_data"
        assert f.independence_group == "market-aggregators"


def test_normalize_invalid_whole_row_and_unknown_source():
    from app.opportunity.economic_normalizers import (
        EconomicNormalizationError,
        normalize_provider_payload,
    )

    with pytest.raises(EconomicNormalizationError):
        normalize_provider_payload(
            source_id="defillama",
            raw_data={"tvl": 1, "change_7d_unit": "percent"},
            source_url="https://defillama.com/x",
            observed_at=OBSERVED,
            expires_at=EXPIRES,
        )
    with pytest.raises(EconomicNormalizationError):
        normalize_provider_payload(
            source_id="coingecko",
            raw_data={"market_cap": "not-a-number"},
            source_url="https://api.coingecko.com/x",
            observed_at=OBSERVED,
            expires_at=EXPIRES,
        )
    with pytest.raises(EconomicNormalizationError):
        normalize_provider_payload(
            source_id="unknown_provider",
            raw_data={"market_cap": 1},
            source_url="https://example.com",
            observed_at=OBSERVED,
            expires_at=EXPIRES,
        )


def test_normalized_observation_accepts_factor_tuple():
    from app.opportunity.economic_normalizers import normalize_provider_payload

    factors = normalize_provider_payload(
        source_id="coingecko",
        raw_data={"market_cap": 1, "market_cap_rank": 3},
        source_url="https://api.coingecko.com/x",
        observed_at=OBSERVED,
        expires_at=EXPIRES,
    )
    obs = NormalizedObservation(
        snapshot_id="snap1",
        source_id="coingecko",
        dedup_key="coingecko:bitcoin",
        provider_entity_id="bitcoin",
        factors=factors,
        collected_at=OBSERVED,
        source_url="https://api.coingecko.com/x",
    )
    assert obs.factors == factors
    assert isinstance(obs.factors, tuple)
