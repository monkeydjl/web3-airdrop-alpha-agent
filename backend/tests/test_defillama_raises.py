"""Unit tests for DefiLlama raises & fundraising mining service."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.services.defillama_raises import (
    DEFILLAMA_BASE_URL,
    build_protocols_slug_map,
    fetch_protocol_funding,
    match_protocol_slug,
    parse_defillama_raises,
)


def test_parse_defillama_raises_empty() -> None:
    """Empty raises list returns standard zero funding dictionary."""
    res = parse_defillama_raises([])
    assert res["has_funding"] is False
    assert res["total_raised"] == 0.0
    assert res["funding_amount"] == 0.0
    assert res["funding_tier"] == "none"
    assert res["round_count"] == 0
    assert res["investors"] == []
    assert res["last_round_date"] is None


def test_parse_defillama_raises_single_round() -> None:
    """Single seed round with Paradigm correctly identifies Tier-1 and $5M amount."""
    raw = [
        {
            "name": "SuperZK",
            "round": "Seed",
            "amount": 5.0,  # 5 million USD
            "date": 1700000000,
            "leadInvestors": ["Paradigm"],
            "otherInvestors": ["Robot Ventures", "1kx"],
            "valuation": 50.0,
        }
    ]
    res = parse_defillama_raises(raw)
    assert res["has_funding"] is True
    assert res["total_raised"] == 5_000_000.0
    assert res["funding_amount"] == 5_000_000.0
    assert res["funding_tier"] == "tier1"
    assert res["round_count"] == 1
    assert "Seed" in res["rounds"]
    assert res["lead_investors"] == ["Paradigm"]
    assert set(res["investors"]) == {"Paradigm", "Robot Ventures", "1kx"}
    assert res["last_round_date"] is not None
    assert res["valuation"] == 50_000_000.0


def test_parse_defillama_raises_multi_rounds_tier_upgrade() -> None:
    """Multiple rounds cumulative amount and tier upgrade from Tier-2 to Tier-1."""
    raw = [
        {
            "round": "Pre-Seed",
            "amount": 1.5,
            "date": 1650000000,
            "leadInvestors": ["Hack VC"],
            "otherInvestors": ["Fenbushi Capital"],
        },
        {
            "round": "Series A",
            "amount": 12.0,
            "date": 1710000000,
            "leadInvestors": ["a16z"],
            "otherInvestors": ["Polychain", "Dragonfly"],
            "valuation": 100.0,
        },
    ]
    res = parse_defillama_raises(raw)
    assert res["has_funding"] is True
    assert res["total_raised"] == 13_500_000.0
    assert res["funding_tier"] == "tier1"
    assert res["round_count"] == 2
    assert "Pre-Seed" in res["rounds"]
    assert "Series A" in res["rounds"]
    assert "Hack VC" in res["lead_investors"]
    assert "a16z" in res["lead_investors"]
    assert res["valuation"] == 100_000_000.0


def test_build_protocols_slug_map_and_match() -> None:
    """Slug map matches by exact name, slug, normalized name, and stripped name."""
    protocols = [
        {"name": "Uniswap", "slug": "uniswap"},
        {"name": "Aave V3", "slug": "aave-v3"},
        {"name": "LayerX Finance", "slug": "layerx"},
        {"name": "Berachain BEX", "slug": "berachain-bex"},
    ]
    slug_map = build_protocols_slug_map(protocols)

    assert match_protocol_slug("Uniswap", slug_map) == "uniswap"
    assert match_protocol_slug("uniswap", slug_map) == "uniswap"
    assert match_protocol_slug("Aave V3", slug_map) == "aave-v3"
    assert match_protocol_slug("aave-v3", slug_map) == "aave-v3"
    assert match_protocol_slug("LayerX", slug_map) == "layerx"
    assert match_protocol_slug("Layer-X Finance", slug_map) == "layerx"
    assert match_protocol_slug("NonExistentProtocol", slug_map) is None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_protocol_funding_success() -> None:
    """fetch_protocol_funding calls /protocol/{slug} and parses raises successfully."""
    mock_payload = {
        "id": "2196",
        "name": "Uniswap",
        "slug": "uniswap",
        "treasury": 50000000,
        "twitter": "Uniswap",
        "github": ["uniswap"],
        "raises": [
            {
                "round": "Series A",
                "amount": 11.0,
                "date": 1596758400,
                "leadInvestors": ["a16z"],
                "otherInvestors": ["Paradigm", "USV", "Variant"],
            }
        ],
    }
    respx.get(f"{DEFILLAMA_BASE_URL}/protocol/uniswap").respond(
        status_code=200,
        json=mock_payload,
    )

    async with httpx.AsyncClient() as client:
        res = await fetch_protocol_funding("uniswap", client=client)

    assert res is not None
    assert res["has_funding"] is True
    assert res["total_raised"] == 11_000_000.0
    assert res["funding_tier"] == "tier1"
    assert res["treasury"] == 50000000
    assert res["twitter"] == "Uniswap"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_protocol_funding_404_returns_none() -> None:
    """fetch_protocol_funding gracefully returns None on 404."""
    respx.get(f"{DEFILLAMA_BASE_URL}/protocol/unknown-slug").respond(status_code=404)

    async with httpx.AsyncClient() as client:
        res = await fetch_protocol_funding("unknown-slug", client=client)

    assert res is None
