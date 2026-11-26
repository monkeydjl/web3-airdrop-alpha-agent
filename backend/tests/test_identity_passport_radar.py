"""Tests for Web3 Identity & Passport Radar (including live on-chain verification)."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.identity_passport_radar import (
    evaluate_wallet_identity,
    evaluate_wallet_identity_live,
    get_stamping_guide,
)


def _encode_abi_single_string_array(text: str) -> str:
    encoded = text.encode("utf-8")
    pad_len = (32 - (len(encoded) % 32)) % 32
    padded_str = encoded + (b"\x00" * pad_len)
    parts = [
        (32).to_bytes(32, "big"),  # offset to array
        (1).to_bytes(32, "big"),  # array length = 1
        (32).to_bytes(32, "big"),  # element[0] relative offset
        len(encoded).to_bytes(32, "big"),  # string byte length
        padded_str,
    ]
    return "0x" + b"".join(parts).hex()


def test_get_stamping_guide() -> None:
    guide = get_stamping_guide()
    assert len(guide) >= 8
    first = guide[0]
    assert "weight" in first
    assert "cost_usd" in first


def test_evaluate_wallet_identity() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    res = evaluate_wallet_identity(addr)
    assert res["wallet_address"] == addr
    assert "passport_score" in res
    assert res["passport_score"] >= 0
    assert "is_human_verified" in res
    assert len(res["active_stamps"]) > 0 or len(res["missing_stamps"]) > 0
    assert "recommended_next_stamps" in res


@respx.mock
@pytest.mark.asyncio
async def test_evaluate_wallet_identity_live_verifies_onchain_and_declared_stamps() -> None:
    wallet = "0xabcdef1234567890abcdef1234567890abcdef12"
    ens_hex = _encode_abi_single_string_array("alpha-hunter.eth")

    def _mainnet_handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content.decode("utf-8"))
        if body["method"] == "eth_call":
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": ens_hex})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x"})

    respx.post("https://ethereum-rpc.publicnode.com").mock(side_effect=_mainnet_handler)
    respx.post("https://arb1.arbitrum.io/rpc").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x6080604052"})
    )
    respx.post("https://mainnet.base.org").mock(
        return_value=httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x"})
    )
    respx.get(f"https://poh-api.linea.build/poh/v2/{wallet}").mock(return_value=httpx.Response(200, text="true"))
    respx.post("https://hub.snapshot.org/graphql").mock(
        return_value=httpx.Response(200, json={"data": {"votes": [{"id": "v1"}, {"id": "v2"}]}})
    )

    result, is_live = await evaluate_wallet_identity_live(
        wallet,
        declared_stamps=["stamp_github", "stamp_holonym"],
        allow_live=True,
    )
    assert is_live is True
    assert result["verification_mode"] == "live_onchain_plus_declared"
    active_ids = {s["id"] for s in result["active_stamps"]}
    assert active_ids == {
        "stamp_ens",
        "stamp_linea_poh",
        "stamp_snapshot",
        "stamp_safe",
        "stamp_github",
        "stamp_holonym",
    }
    assert result["is_human_verified"] is True
    assert result["onchain_verification"]["ens_name"] == "alpha-hunter.eth"
    assert result["onchain_verification"]["linea_poh_verified"] is True
    assert result["onchain_verification"]["contract_wallet_chains"] == ["arbitrum"]


@respx.mock
@pytest.mark.asyncio
async def test_evaluate_wallet_identity_live_falls_back_when_all_probes_fail() -> None:
    wallet = "0x9999999999999999999999999999999999999999"
    respx.post("https://ethereum-rpc.publicnode.com").mock(side_effect=httpx.ConnectTimeout("timeout"))
    respx.post("https://arb1.arbitrum.io/rpc").mock(side_effect=httpx.ConnectTimeout("timeout"))
    respx.post("https://mainnet.base.org").mock(side_effect=httpx.ConnectTimeout("timeout"))
    respx.get(f"https://poh-api.linea.build/poh/v2/{wallet}").mock(side_effect=httpx.ConnectTimeout("timeout"))
    respx.post("https://hub.snapshot.org/graphql").mock(side_effect=httpx.ConnectTimeout("timeout"))

    result, is_live = await evaluate_wallet_identity_live(wallet, allow_live=True)
    assert is_live is False
    assert "onchain_verification" not in result


def test_identity_router_marks_real_with_declared_stamps() -> None:
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/identity/evaluate",
            json={
                "wallet_address": "0x1234567890123456789012345678901234567890",
                "declared_stamps": ["stamp_github", "stamp_twitter", "stamp_holonym"],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_quality"]["quality"] == "real"
        assert {s["id"] for s in body["data"]["active_stamps"]} == {
            "stamp_github",
            "stamp_twitter",
            "stamp_holonym",
        }
