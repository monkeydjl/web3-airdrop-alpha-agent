"""Task 1: economic feature flags, frozen models, and canonical hash helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from types import MappingProxyType
from typing import get_args, get_type_hints

import pytest
from pydantic import ValidationError

from app.config import Settings


def _utc(ts: str = "2026-07-22T12:00:00+00:00") -> datetime:
    return datetime.fromisoformat(ts).astimezone(UTC)


# ── Settings flags ──────────────────────────────────────────────


def test_economic_flags_default_false():
    settings = Settings(
        opportunity_economic_snapshot_enabled=False,
        opportunity_economic_source_defillama_enabled=False,
        opportunity_economic_source_coingecko_enabled=False,
        opportunity_economic_source_cryptorank_enabled=False,
        opportunity_economic_evidence_emit_enabled=False,
        opportunity_economic_resolver_enabled=False,
    )
    assert settings.opportunity_economic_snapshot_enabled is False
    assert settings.opportunity_economic_source_defillama_enabled is False
    assert settings.opportunity_economic_source_coingecko_enabled is False
    assert settings.opportunity_economic_source_cryptorank_enabled is False
    assert settings.opportunity_economic_evidence_emit_enabled is False
    assert settings.opportunity_economic_resolver_enabled is False


def test_economic_flag_defaults_are_false_when_omitted():
    settings = Settings()
    assert settings.opportunity_economic_snapshot_enabled is False
    assert settings.opportunity_economic_source_defillama_enabled is False
    assert settings.opportunity_economic_source_coingecko_enabled is False
    assert settings.opportunity_economic_source_cryptorank_enabled is False
    assert settings.opportunity_economic_evidence_emit_enabled is False
    assert settings.opportunity_economic_resolver_enabled is False


def test_evidence_emit_requires_snapshot():
    with pytest.raises(ValidationError):
        Settings(
            opportunity_economic_snapshot_enabled=False,
            opportunity_economic_evidence_emit_enabled=True,
        )


def test_resolver_requires_evidence_emit():
    with pytest.raises(ValidationError):
        Settings(
            opportunity_economic_snapshot_enabled=True,
            opportunity_economic_evidence_emit_enabled=False,
            opportunity_economic_resolver_enabled=True,
        )


def test_all_six_economic_flags_may_be_enabled_together():
    settings = Settings(
        opportunity_economic_snapshot_enabled=True,
        opportunity_economic_source_defillama_enabled=True,
        opportunity_economic_source_coingecko_enabled=True,
        opportunity_economic_source_cryptorank_enabled=True,
        opportunity_economic_evidence_emit_enabled=True,
        opportunity_economic_resolver_enabled=True,
    )
    assert settings.opportunity_economic_snapshot_enabled is True
    assert settings.opportunity_economic_source_defillama_enabled is True
    assert settings.opportunity_economic_source_coingecko_enabled is True
    assert settings.opportunity_economic_source_cryptorank_enabled is True
    assert settings.opportunity_economic_evidence_emit_enabled is True
    assert settings.opportunity_economic_resolver_enabled is True


# ── Frozen models ───────────────────────────────────────────────


def test_schema_version_constant_and_value_type_closed_set():
    from app.opportunity.economic_models import SCHEMA_VERSION, ValueType

    assert SCHEMA_VERSION == "opportunity-economic-snapshot-v1"
    assert get_args(ValueType) == ("bool", "number", "string", "json")
    assert "boolean" not in get_args(ValueType)
    assert "null" not in get_args(ValueType)


def test_normalized_factor_sample_and_closed_enums_deep_freeze():
    from app.opportunity.economic_models import NormalizedFactor

    observed = _utc()
    expires = _utc("2026-07-24T12:00:00+00:00")
    factor = NormalizedFactor(
        factor_key="tvl_usd",
        value="1.50000000",
        value_type="string",
        unit="usd",
        source_type="public_aggregator",
        source_grade="C",
        verification_status="verified",
        independence_group="defillama-protocols",
        source_url="https://api.llama.fi/protocol/example",
        observed_at=observed,
        expires_at=expires,
    )
    assert factor.factor_key == "tvl_usd"
    assert factor.value == "1.50000000"
    assert factor.value_type == "string"
    assert factor.unit == "usd"
    assert factor.source_type == "public_aggregator"
    assert factor.source_grade == "C"
    assert factor.verification_status == "verified"
    assert factor.independence_group == "defillama-protocols"
    assert set(get_args(get_type_hints(NormalizedFactor)["source_grade"])) == {
        "A",
        "B",
        "C",
        "D",
        "U",
    }
    assert set(get_args(get_type_hints(NormalizedFactor)["verification_status"])) == {
        "verified",
        "partially_verified",
        "unverified",
        "conflicted",
        "invalidated",
    }

    with pytest.raises(ValidationError):
        NormalizedFactor(
            factor_key="tvl_usd",
            value="1.50000000",
            value_type="boolean",
            unit="usd",
            source_type="public_aggregator",
            independence_group="defillama-protocols",
            source_url="https://api.llama.fi/protocol/example",
            observed_at=observed,
            expires_at=expires,
        )
    with pytest.raises(ValidationError):
        NormalizedFactor(
            factor_key="tvl_usd",
            value="1.50000000",
            value_type="null",
            unit="usd",
            source_type="public_aggregator",
            independence_group="defillama-protocols",
            source_url="https://api.llama.fi/protocol/example",
            observed_at=observed,
            expires_at=expires,
        )
    with pytest.raises(ValidationError):
        NormalizedFactor(
            factor_key="tvl_usd",
            value="1.50000000",
            value_type="string",
            unit="usd",
            source_type="public_aggregator",
            source_grade="Z",  # type: ignore[arg-type]
            independence_group="defillama-protocols",
            source_url="https://api.llama.fi/protocol/example",
            observed_at=observed,
            expires_at=expires,
        )
    with pytest.raises(ValidationError):
        NormalizedFactor(
            factor_key="tvl_usd",
            value="1.50000000",
            value_type="string",
            unit="usd",
            source_type="public_aggregator",
            verification_status="unknown",  # type: ignore[arg-type]
            independence_group="defillama-protocols",
            source_url="https://api.llama.fi/protocol/example",
            observed_at=observed,
            expires_at=expires,
        )

    nested = NormalizedFactor(
        factor_key="chains_json",
        value={"chains": ["ethereum", "base"], "meta": {"n": 2}},
        value_type="json",
        unit=None,
        source_type="public_aggregator",
        independence_group="defillama-protocols",
        source_url="https://api.llama.fi/protocol/example",
        observed_at=observed,
        expires_at=expires,
    )
    assert isinstance(nested.value, MappingProxyType)
    assert isinstance(nested.value["meta"], MappingProxyType)
    assert nested.value["chains"] == ("ethereum", "base")
    with pytest.raises(TypeError):
        nested.value["x"] = 1  # type: ignore[index]
    with pytest.raises(ValidationError):
        nested.factor_key = "mutated"  # type: ignore[misc]


def test_economic_snapshot_row_and_observation_contract():
    from app.opportunity.economic_models import (
        SCHEMA_VERSION,
        EconomicSnapshotRow,
        NormalizedFactor,
        NormalizedObservation,
        payload_sha256,
    )

    observed = _utc()
    expires = _utc("2026-07-24T12:00:00+00:00")
    provider_payload = {
        "tvl": 0,
        "change_7d": 0.01,
        "change_7d_unit": "ratio",
        "chains": ["ethereum"],
        "no_token_yet": True,
    }
    digest = payload_sha256(provider_payload)
    row = EconomicSnapshotRow(
        snapshot_id="a" * 64,
        schema_version=SCHEMA_VERSION,
        run_id="2026-07-22",
        source_id="defillama",
        dedup_key="  keep-spaces  ",
        provider_entity_id="raw-protocol-1",
        payload_sha256=digest,
        payload_json=provider_payload,
        collected_at=observed,
        source_url="https://api.llama.fi/protocol/example",
    )
    assert list(EconomicSnapshotRow.model_fields) == [
        "snapshot_id",
        "schema_version",
        "run_id",
        "source_id",
        "dedup_key",
        "provider_entity_id",
        "payload_sha256",
        "payload_json",
        "collected_at",
        "source_url",
    ]
    assert row.schema_version == "opportunity-economic-snapshot-v1"
    assert row.dedup_key == "  keep-spaces  "
    assert row.provider_entity_id == "raw-protocol-1"
    assert isinstance(row.payload_json, MappingProxyType)
    assert row.payload_json["tvl"] == 0
    with pytest.raises(TypeError):
        row.payload_json["tvl"] = 99  # type: ignore[index]
    with pytest.raises(ValidationError):
        EconomicSnapshotRow(
            snapshot_id="b" * 64,
            schema_version="wrong-schema",
            run_id="2026-07-22",
            source_id="defillama",
            dedup_key="k",
            provider_entity_id="raw-1",
            payload_sha256=digest,
            payload_json=provider_payload,
            collected_at=observed,
            source_url="https://example.com",
        )

    factor = NormalizedFactor(
        factor_key="tvl_usd",
        value="0.00000000",
        value_type="string",
        unit="usd",
        source_type="public_aggregator",
        independence_group="defillama-protocols",
        source_url="https://api.llama.fi/protocol/example",
        observed_at=observed,
        expires_at=expires,
    )
    observation = NormalizedObservation(
        snapshot_id=row.snapshot_id,
        source_id=row.source_id,
        dedup_key=row.dedup_key,
        provider_entity_id=row.provider_entity_id,
        factors=(factor,),
        collected_at=row.collected_at,
        source_url=row.source_url,
    )
    assert list(NormalizedObservation.model_fields) == [
        "snapshot_id",
        "source_id",
        "dedup_key",
        "provider_entity_id",
        "factors",
        "collected_at",
        "source_url",
    ]
    assert observation.dedup_key == "  keep-spaces  "
    assert observation.provider_entity_id == "raw-protocol-1"
    assert isinstance(observation.factors, tuple)
    with pytest.raises(TypeError):
        observation.factors[0] = factor  # type: ignore[index]
    with pytest.raises(ValidationError):
        NormalizedObservation(
            snapshot_id=row.snapshot_id,
            source_id=row.source_id,
            dedup_key="",
            provider_entity_id=row.provider_entity_id,
            factors=(factor,),
            collected_at=row.collected_at,
            source_url=row.source_url,
        )
    with pytest.raises(ValidationError):
        NormalizedObservation(
            snapshot_id=row.snapshot_id,
            source_id=row.source_id,
            dedup_key="   ",
            provider_entity_id=row.provider_entity_id,
            factors=(factor,),
            collected_at=row.collected_at,
            source_url=row.source_url,
        )
    with pytest.raises(ValidationError):
        EconomicSnapshotRow(
            snapshot_id="c" * 64,
            schema_version=SCHEMA_VERSION,
            run_id="2026-07-22",
            source_id="defillama",
            dedup_key="   ",
            provider_entity_id="raw-1",
            payload_sha256=digest,
            payload_json=provider_payload,
            collected_at=observed,
            source_url="https://example.com",
        )


# ── Canonical hash helpers (four function families) ─────────────


def test_canonical_json_bytes_unicode_mappingproxy_sort_and_nan():
    from app.opportunity.economic_models import canonical_json_bytes

    frozen = MappingProxyType({"b": 1, "a": MappingProxyType({"中文": "值"}), "z": (1, 2)})
    raw = canonical_json_bytes(frozen)
    assert isinstance(raw, bytes)
    assert raw == json.dumps(
        {"a": {"中文": "值"}, "b": 1, "z": [1, 2]},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    # real zero preserved; None key still serializable if present (omit-None is caller contract)
    assert b'"tvl":0' in canonical_json_bytes({"tvl": 0, "change_7d_unit": "ratio"})
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float("nan")})
    with pytest.raises(ValueError):
        canonical_json_bytes({"x": float("inf")})


def test_hash_string_array_order_non_str_and_lowercase_64():
    from app.opportunity.economic_models import hash_string_array

    digest = hash_string_array(["schema", "run", "source"])
    assert len(digest) == 64
    assert digest == digest.lower()
    assert all(c in "0123456789abcdef" for c in digest)
    assert (
        digest
        == hashlib.sha256(
            json.dumps(["schema", "run", "source"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
    )
    # fixed order: reordering inputs must change digest
    assert hash_string_array(["a", "b"]) != hash_string_array(["b", "a"])
    with pytest.raises((TypeError, ValueError)):
        hash_string_array(["ok", 1])  # type: ignore[list-item]
    with pytest.raises((TypeError, ValueError)):
        hash_string_array([None])  # type: ignore[list-item]


def test_payload_sha256_hashes_canonical_provider_native_object():
    from app.opportunity.economic_models import canonical_json_bytes, payload_sha256

    base = {
        "tvl": 0,
        "change_7d": 0.05,
        "change_7d_unit": "ratio",
        "chains": ["ethereum", "base"],
        "no_token_yet": True,
    }
    # MappingProxy and key order must not change digest
    digest_a = payload_sha256(base)
    digest_b = payload_sha256(MappingProxyType(dict(reversed(list(base.items())))))
    assert digest_a == digest_b
    assert len(digest_a) == 64
    assert digest_a == digest_a.lower()
    assert digest_a == hashlib.sha256(canonical_json_bytes(base)).hexdigest()
    # payload change changes hash; real zero kept distinct from missing
    changed = {**base, "tvl": 1}
    assert payload_sha256(changed) != digest_a
    without_zero = {k: v for k, v in base.items() if k != "tvl"}
    assert payload_sha256(without_zero) != digest_a
    # Defi unit participates in hash
    without_unit = {k: v for k, v in base.items() if k != "change_7d_unit"}
    assert payload_sha256(without_unit) != digest_a


def test_build_snapshot_and_evidence_id_array_framing():
    from app.opportunity.economic_models import (
        SCHEMA_VERSION,
        build_evidence_id,
        build_snapshot_id,
        hash_string_array,
        payload_sha256,
    )

    payload_hex = payload_sha256(
        {
            "tvl": 0,
            "change_7d_unit": "ratio",
            "no_token_yet": False,
        }
    )
    snapshot_id = build_snapshot_id(
        run_id="2026-07-22",
        source_id="defillama",
        provider_entity_id="raw-protocol-1",
        payload_sha256_hex=payload_hex,
    )
    assert snapshot_id == hash_string_array(
        [
            SCHEMA_VERSION,
            "2026-07-22",
            "defillama",
            "raw-protocol-1",
            payload_hex,
        ]
    )
    assert len(snapshot_id) == 64
    assert snapshot_id == snapshot_id.lower()

    evidence_id = build_evidence_id(
        snapshot_id=snapshot_id,
        project_id="proj-1",
        factor_key="tvl_usd",
    )
    assert evidence_id == hash_string_array([SCHEMA_VERSION, snapshot_id, "proj-1", "tvl_usd"])
    assert len(evidence_id) == 64
    assert evidence_id == evidence_id.lower()
    # component order is fixed: different argument order cannot silently match
    assert snapshot_id != hash_string_array(
        [
            SCHEMA_VERSION,
            "defillama",
            "2026-07-22",
            "raw-protocol-1",
            payload_hex,
        ]
    )
