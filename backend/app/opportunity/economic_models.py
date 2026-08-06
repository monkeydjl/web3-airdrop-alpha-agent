"""Frozen opportunity-economic snapshot/observation models and canonical hash helpers.

Task 1 only: schema contracts and pure hash framing. No network, no repository,
no Evidence emit, no provider normalizers.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from math import isfinite
from types import MappingProxyType
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SCHEMA_VERSION: Final[Literal["opportunity-economic-snapshot-v1"]] = "opportunity-economic-snapshot-v1"
ValueType = Literal["bool", "number", "string", "json"]
EconomicsDataMode = Literal["PROXY_ONLY", "DIRECT_AVAILABLE", "UNKNOWN"]

_SOURCE_GRADE = Literal["A", "B", "C", "D", "U"]
_VERIFICATION_STATUS = Literal[
    "verified",
    "partially_verified",
    "unverified",
    "conflicted",
    "invalidated",
]


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        if not all(isinstance(key, str) for key in value):
            raise ValueError("JSON object keys must be strings")
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not isfinite(value):
        raise ValueError("JSON numbers must be finite")
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise ValueError("expected a JSON-like value")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _reject_blank(value: str) -> str:
    if not isinstance(value, str) or len(value.strip()) == 0:
        raise ValueError("must be a non-blank string")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Recursive thaw → sort_keys canonical JSON → UTF-8 bytes; reject non-finite floats."""

    def _prepare(obj: Any) -> Any:
        if isinstance(obj, Mapping):
            if not all(isinstance(key, str) for key in obj):
                raise ValueError("JSON object keys must be strings")
            return {key: _prepare(item) for key, item in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_prepare(item) for item in obj]
        if isinstance(obj, float):
            if not math.isfinite(obj):
                raise ValueError("JSON numbers must be finite")
            return obj
        if obj is None or isinstance(obj, (bool, int, str)):
            return obj
        raise ValueError("expected a JSON-like value")

    prepared = _prepare(value)
    return json.dumps(
        prepared,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def hash_string_array(parts: Sequence[str]) -> str:
    """§5.0 framing: fixed-order JSON string array → SHA-256 lowercase 64 hex."""
    if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
        raise TypeError("parts must be a sequence of strings")
    materialised = list(parts)
    if not all(isinstance(part, str) for part in materialised):
        raise TypeError("hash_string_array rejects non-str parts")
    digest = hashlib.sha256(
        json.dumps(materialised, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest.lower()


def payload_sha256(payload: Mapping[str, Any]) -> str:
    """Hash the exact §4.3 provider-native canonical payload object.

    Callers must already pass a whitelist-trimmed object (omit None, preserve real
    zero, include DefiLlama unit). This function does not delete fields.
    """
    if not isinstance(payload, Mapping):
        raise TypeError("payload must be a Mapping")
    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest().lower()


def build_snapshot_id(
    *,
    run_id: str,
    source_id: str,
    provider_entity_id: str,
    payload_sha256_hex: str,
) -> str:
    """§5.1 five-component array framing."""
    return hash_string_array(
        [
            SCHEMA_VERSION,
            run_id,
            source_id,
            provider_entity_id,
            payload_sha256_hex,
        ]
    )


def build_evidence_id(
    *,
    snapshot_id: str,
    project_id: str,
    factor_key: str,
) -> str:
    """§5.2 four-component array framing."""
    return hash_string_array(
        [
            SCHEMA_VERSION,
            snapshot_id,
            project_id,
            factor_key,
        ]
    )


class EconomicSnapshotRow(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    snapshot_id: str
    schema_version: Literal["opportunity-economic-snapshot-v1"]
    run_id: str
    source_id: str
    dedup_key: str
    provider_entity_id: str
    payload_sha256: str
    payload_json: Any
    collected_at: datetime
    source_url: str

    @field_validator("dedup_key")
    @classmethod
    def dedup_key_non_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("payload_json", mode="before")
    @classmethod
    def freeze_payload_json(cls, value: Any) -> Any:
        return _freeze_json(value)


class NormalizedFactor(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    factor_key: str
    value: Any
    value_type: ValueType
    unit: str | None
    source_type: str
    source_grade: _SOURCE_GRADE = "C"
    verification_status: _VERIFICATION_STATUS = "verified"
    independence_group: str
    source_url: str
    observed_at: datetime
    expires_at: datetime

    @field_validator("value", mode="before")
    @classmethod
    def freeze_value(cls, value: Any) -> Any:
        return _freeze_json(value)


class NormalizedObservation(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    snapshot_id: str
    source_id: str
    dedup_key: str
    provider_entity_id: str  # RawDiscovery.raw_id
    factors: tuple[NormalizedFactor, ...]
    collected_at: datetime
    source_url: str

    @field_validator("dedup_key")
    @classmethod
    def dedup_key_non_blank(cls, value: str) -> str:
        return _reject_blank(value)

    @field_validator("factors", mode="before")
    @classmethod
    def factors_as_tuple(cls, value: Any) -> Any:
        if value is None:
            return ()
        if isinstance(value, NormalizedFactor):
            return (value,)
        return tuple(value)

    @model_validator(mode="after")
    def factors_must_be_tuple(self):
        if not isinstance(self.factors, tuple):
            raise ValueError("factors must be a tuple")
        return self


# ── Task 6: internal economic proxy projection DTOs ──────────────


@dataclass(frozen=True)
class ResolvedEconomicFactor:
    factor_key: str
    value: Any | None
    value_type: Literal["bool", "number", "string", "json"]
    evidence_id: str | None
    conflicted: bool

    def __post_init__(self) -> None:
        if self.value is not None:
            object.__setattr__(self, "value", _freeze_json(self.value))


@dataclass(frozen=True)
class EconomicProxyProjection:
    factors: Mapping[str, ResolvedEconomicFactor]
    economics_data_mode: EconomicsDataMode

    def __post_init__(self) -> None:
        frozen = MappingProxyType(dict(self.factors))
        object.__setattr__(self, "factors", frozen)
