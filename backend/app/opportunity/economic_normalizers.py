"""Provider-specific economic field normalizers (Task 3).

Whitelist-only canonical payloads and factor mapping. No network, no clients,
no writer/evidence/resolver side effects.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from types import MappingProxyType
from typing import Any, Final, Literal, cast
from urllib.parse import urlsplit, urlunsplit

from app.opportunity.economic_models import NormalizedFactor

DEFILLAMA_CHANGE_7D_PROVIDER_UNIT: Final[Literal["ratio"]] = "ratio"

_EIGHT_PLACES = Decimal("0.00000001")

PROVIDER_RAW_FIELD_KEYS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "defillama": frozenset({"tvl", "change_7d", "change_7d_unit", "chains", "no_token_yet"}),
        "coingecko": frozenset(
            {
                "market_cap",
                "current_price",
                "total_volume",
                "circulating_supply",
                "market_cap_rank",
                "price_change_percentage_24h",
            }
        ),
        "cryptorank": frozenset(
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
        ),
    }
)

_SOURCE_META: Mapping[str, tuple[str, str]] = MappingProxyType(
    {
        "defillama": ("public_aggregator", "defillama-protocols"),
        "coingecko": ("public_market_data", "market-aggregators"),
        "cryptorank": ("public_market_data", "market-aggregators"),
    }
)


class EconomicNormalizationError(ValueError):
    """Schema-invalid economic row or field (whole-row failure semantics)."""


def normalize_decimal_string(value: Any, *, nonnegative: bool) -> str:
    if isinstance(value, bool) or value is None:
        raise EconomicNormalizationError("decimal value must be a finite non-bool number")
    if isinstance(value, str) and len(value.strip()) == 0:
        raise EconomicNormalizationError("decimal value must not be blank")
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EconomicNormalizationError(f"invalid decimal: {value!r}") from exc
    if not decimal_value.is_finite():
        raise EconomicNormalizationError("decimal value must be finite")
    if nonnegative and decimal_value < 0:
        raise EconomicNormalizationError("decimal value must be nonnegative")
    quantized = decimal_value.quantize(_EIGHT_PLACES, rounding=ROUND_HALF_EVEN)
    # Fixed 8-place decimal string, never scientific notation.
    return format(quantized, "f")


def normalize_ratio_string(value: Any, *, divisor: Decimal = Decimal("1")) -> str:
    if isinstance(value, bool) or value is None:
        raise EconomicNormalizationError("ratio value must be a finite non-bool number")
    if isinstance(value, str) and len(value.strip()) == 0:
        raise EconomicNormalizationError("ratio value must not be blank")
    try:
        decimal_value = Decimal(str(value))
        div = Decimal(divisor) if not isinstance(divisor, Decimal) else divisor
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise EconomicNormalizationError(f"invalid ratio: {value!r}") from exc
    if not decimal_value.is_finite() or not div.is_finite() or div == 0:
        raise EconomicNormalizationError("ratio inputs must be finite with nonzero divisor")
    ratio = decimal_value / div
    quantized = ratio.quantize(_EIGHT_PLACES, rounding=ROUND_HALF_EVEN)
    return format(quantized, "f")


def normalize_market_rank(value: Any) -> int:
    if isinstance(value, bool) or value is None:
        raise EconomicNormalizationError("market_rank must be a non-bool integer")
    if isinstance(value, float):
        if not value.is_integer():
            raise EconomicNormalizationError("market_rank must be an integer")
        value = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped or "." in stripped or "e" in stripped.lower():
            raise EconomicNormalizationError("market_rank must be an integer")
        try:
            value = int(stripped)
        except (TypeError, ValueError) as exc:
            raise EconomicNormalizationError(f"invalid market_rank: {value!r}") from exc
    elif not isinstance(value, int):
        raise EconomicNormalizationError("market_rank must be an integer")
    if value < 0:
        raise EconomicNormalizationError("market_rank must be nonnegative")
    return cast(int, value)


def normalize_chains_json(value: Any) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise EconomicNormalizationError("chains must be a non-empty string array")
    if len(value) == 0:
        raise EconomicNormalizationError("chains must be non-empty")
    stripped: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise EconomicNormalizationError("chains entries must be strings")
        s = item.strip()
        if not s:
            raise EconomicNormalizationError("chains entries must be non-blank")
        stripped.append(s)
    if len(set(stripped)) != len(stripped):
        raise EconomicNormalizationError("chains must not contain duplicates")
    return tuple(sorted(stripped))


def normalize_strict_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise EconomicNormalizationError("value must be a strict bool")
    return value


def sanitize_source_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise EconomicNormalizationError("source_url must be a non-blank string")
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"}:
        raise EconomicNormalizationError("source_url must be http(s)")
    if parts.username is not None or parts.password is not None:
        raise EconomicNormalizationError("source_url must not contain userinfo")
    # Drop entire query and fragment.
    return urlunsplit((scheme, parts.netloc, parts.path, "", ""))


def canonical_provider_payload(source_id: str, raw_data: Mapping[str, Any]) -> dict[str, Any]:
    if source_id not in PROVIDER_RAW_FIELD_KEYS:
        raise EconomicNormalizationError(f"unknown source_id: {source_id}")
    if not isinstance(raw_data, Mapping):
        raise EconomicNormalizationError("raw_data must be a mapping")

    allowed = PROVIDER_RAW_FIELD_KEYS[source_id]
    payload: dict[str, Any] = {}
    for key in allowed:
        if key not in raw_data:
            continue
        value = raw_data[key]
        if value is None:
            continue
        payload[key] = value

    if source_id == "defillama":
        unit = payload.get("change_7d_unit")
        if unit != DEFILLAMA_CHANGE_7D_PROVIDER_UNIT:
            # Missing / None (already omitted) / other value → whole-row invalid.
            raise EconomicNormalizationError("defillama change_7d_unit must be exact literal 'ratio'")

    return payload


def _factor(
    *,
    factor_key: str,
    value: Any,
    value_type: Literal["bool", "number", "string", "json"],
    unit: str | None,
    source_id: str,
    source_url: str,
    observed_at: datetime,
    expires_at: datetime,
) -> NormalizedFactor:
    source_type, independence_group = _SOURCE_META[source_id]
    return NormalizedFactor(
        factor_key=factor_key,
        value=value,
        value_type=value_type,
        unit=unit,
        source_type=source_type,
        source_grade="C",
        verification_status="verified",
        independence_group=independence_group,
        source_url=source_url,
        observed_at=observed_at,
        expires_at=expires_at,
    )


def _map_defillama(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    observed_at: datetime,
    expires_at: datetime,
) -> list[NormalizedFactor]:
    factors: list[NormalizedFactor] = []
    if "tvl" in payload:
        factors.append(
            _factor(
                factor_key="tvl_usd",
                value=normalize_decimal_string(payload["tvl"], nonnegative=True),
                value_type="string",
                unit="usd",
                source_id="defillama",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    if "change_7d" in payload:
        factors.append(
            _factor(
                factor_key="tvl_change_7d_ratio",
                value=normalize_ratio_string(payload["change_7d"], divisor=Decimal("1")),
                value_type="string",
                unit="ratio",
                source_id="defillama",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    # change_7d_unit is payload-only, never a factor.
    if "chains" in payload:
        factors.append(
            _factor(
                factor_key="chains_json",
                value=normalize_chains_json(payload["chains"]),
                value_type="json",
                unit=None,
                source_id="defillama",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    if "no_token_yet" in payload:
        factors.append(
            _factor(
                factor_key="token_unlisted_proxy",
                value=normalize_strict_bool(payload["no_token_yet"]),
                value_type="bool",
                unit=None,
                source_id="defillama",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    return factors


def _map_coingecko(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    observed_at: datetime,
    expires_at: datetime,
) -> list[NormalizedFactor]:
    factors: list[NormalizedFactor] = []
    usd_map = (
        ("market_cap", "market_cap_usd"),
        ("current_price", "price_usd"),
        ("total_volume", "volume_24h_usd"),
    )
    for raw_key, factor_key in usd_map:
        if raw_key in payload:
            factors.append(
                _factor(
                    factor_key=factor_key,
                    value=normalize_decimal_string(payload[raw_key], nonnegative=True),
                    value_type="string",
                    unit="usd",
                    source_id="coingecko",
                    source_url=source_url,
                    observed_at=observed_at,
                    expires_at=expires_at,
                )
            )
    if "circulating_supply" in payload:
        factors.append(
            _factor(
                factor_key="circulating_supply",
                value=normalize_decimal_string(payload["circulating_supply"], nonnegative=True),
                value_type="string",
                unit=None,
                source_id="coingecko",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    if "market_cap_rank" in payload:
        factors.append(
            _factor(
                factor_key="market_rank",
                value=normalize_market_rank(payload["market_cap_rank"]),
                value_type="number",
                unit=None,
                source_id="coingecko",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    # Only price_change_percentage_24h → ratio; never price_change_24h.
    if "price_change_percentage_24h" in payload:
        factors.append(
            _factor(
                factor_key="price_change_24h_ratio",
                value=normalize_ratio_string(payload["price_change_percentage_24h"], divisor=Decimal("100")),
                value_type="string",
                unit="ratio",
                source_id="coingecko",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    return factors


def _map_cryptorank(
    payload: Mapping[str, Any],
    *,
    source_url: str,
    observed_at: datetime,
    expires_at: datetime,
) -> list[NormalizedFactor]:
    factors: list[NormalizedFactor] = []
    usd_map = (
        ("market_cap", "market_cap_usd"),
        ("price", "price_usd"),
        ("volume_24h", "volume_24h_usd"),
    )
    for raw_key, factor_key in usd_map:
        if raw_key in payload:
            factors.append(
                _factor(
                    factor_key=factor_key,
                    value=normalize_decimal_string(payload[raw_key], nonnegative=True),
                    value_type="string",
                    unit="usd",
                    source_id="cryptorank",
                    source_url=source_url,
                    observed_at=observed_at,
                    expires_at=expires_at,
                )
            )
    for raw_key, factor_key in (
        ("circulating_supply", "circulating_supply"),
        ("total_supply", "total_supply"),
    ):
        if raw_key in payload:
            factors.append(
                _factor(
                    factor_key=factor_key,
                    value=normalize_decimal_string(payload[raw_key], nonnegative=True),
                    value_type="string",
                    unit=None,
                    source_id="cryptorank",
                    source_url=source_url,
                    observed_at=observed_at,
                    expires_at=expires_at,
                )
            )
    if "rank" in payload:
        factors.append(
            _factor(
                factor_key="market_rank",
                value=normalize_market_rank(payload["rank"]),
                value_type="number",
                unit=None,
                source_id="cryptorank",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    if "percent_change_24h" in payload:
        factors.append(
            _factor(
                factor_key="price_change_24h_ratio",
                value=normalize_ratio_string(payload["percent_change_24h"], divisor=Decimal("100")),
                value_type="string",
                unit="ratio",
                source_id="cryptorank",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    if "percent_change_7d" in payload:
        factors.append(
            _factor(
                factor_key="price_change_7d_ratio",
                value=normalize_ratio_string(payload["percent_change_7d"], divisor=Decimal("100")),
                value_type="string",
                unit="ratio",
                source_id="cryptorank",
                source_url=source_url,
                observed_at=observed_at,
                expires_at=expires_at,
            )
        )
    return factors


_MAPPERS = {
    "defillama": _map_defillama,
    "coingecko": _map_coingecko,
    "cryptorank": _map_cryptorank,
}


def normalize_provider_payload(
    *,
    source_id: str,
    raw_data: Mapping[str, Any],
    source_url: str,
    observed_at: datetime,
    expires_at: datetime,
) -> tuple[NormalizedFactor, ...]:
    """Whitelist-trim raw_data, map present fields to factors, sort by factor_key.

    Missing fields are not filled. Any invalid field invalidates the whole row.
    """
    if source_id not in _MAPPERS:
        raise EconomicNormalizationError(f"unknown source_id: {source_id}")
    clean_url = sanitize_source_url(source_url)
    payload = canonical_provider_payload(source_id, raw_data)
    try:
        factors = _MAPPERS[source_id](
            payload,
            source_url=clean_url,
            observed_at=observed_at,
            expires_at=expires_at,
        )
    except EconomicNormalizationError:
        raise
    except Exception as exc:  # pragma: no cover - defensive whole-row wrap
        raise EconomicNormalizationError(str(exc)) from exc
    factors.sort(key=lambda f: f.factor_key)
    return tuple(factors)
