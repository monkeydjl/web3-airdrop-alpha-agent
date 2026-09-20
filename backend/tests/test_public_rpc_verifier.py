"""Unit tests for public EVM RPC contract and liveness verifier."""

from __future__ import annotations

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.main import app
from app.services.public_rpc_verifier import (
    is_valid_evm_address,
    verify_contract_liveness,
)


def test_is_valid_evm_address() -> None:
    assert is_valid_evm_address("0x1234567890123456789012345678901234567890") is True
    assert is_valid_evm_address("0xabcdefABCDEF1234567890123456789012345678") is True
    # Invalid addresses
    assert is_valid_evm_address("") is False
    assert is_valid_evm_address("0x123") is False
    assert is_valid_evm_address("1234567890123456789012345678901234567890") is False  # missing 0x
    assert is_valid_evm_address("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG") is False  # non-hex


@pytest.mark.asyncio
async def test_verify_contract_liveness_invalid_address() -> None:
    res = await verify_contract_liveness("invalid-addr", chain="sepolia")
    assert res["is_valid"] is False
    assert res["status"] == "invalid_address"


@pytest.mark.asyncio
async def test_verify_contract_liveness_unsupported_chain() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    res = await verify_contract_liveness(addr, chain="unsupported_network")
    assert res["is_valid"] is True
    assert res["status"] == "unsupported_chain"


@pytest.mark.asyncio
@respx.mock
async def test_verify_contract_liveness_contract_found() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    endpoint = "https://ethereum-sepolia-rpc.publicnode.com"

    # Mock eth_getCode returning non-empty bytecode
    respx.post(endpoint).mock(
        side_effect=[
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x608060405234801561001057600080fd5b50", "id": 1}),
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x5", "id": 2}),
        ]
    )

    res = await verify_contract_liveness(addr, chain="sepolia")
    assert res["is_contract"] is True
    assert res["deployed"] is True
    assert res["bytecode_size"] > 0
    assert res["transaction_count"] == 5
    assert res["status"] == "active"


@pytest.mark.asyncio
@respx.mock
async def test_verify_contract_liveness_empty_eoa() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    endpoint = "https://ethereum-sepolia-rpc.publicnode.com"

    # Mock eth_getCode returning 0x, tx_count returning 0x0
    respx.post(endpoint).mock(
        side_effect=[
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x", "id": 1}),
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x0", "id": 2}),
        ]
    )

    res = await verify_contract_liveness(addr, chain="sepolia")
    assert res["is_contract"] is False
    assert res["deployed"] is False
    assert res["bytecode_size"] == 0
    assert res["transaction_count"] == 0
    assert res["status"] == "empty"


@pytest.mark.asyncio
@respx.mock
async def test_verify_contract_liveness_fallback_endpoint() -> None:
    addr = "0x1234567890123456789012345678901234567890"
    ep1 = "https://ethereum-sepolia-rpc.publicnode.com"
    ep2 = "https://rpc.sepolia.org"

    # First endpoint fails with 500, second succeeds
    respx.post(ep1).mock(return_value=httpx.Response(500))
    respx.post(ep2).mock(
        side_effect=[
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x6080", "id": 1}),
            httpx.Response(200, json={"jsonrpc": "2.0", "result": "0x1", "id": 2}),
        ]
    )

    res = await verify_contract_liveness(addr, chain="sepolia")
    assert res["is_contract"] is True
    assert res["rpc_endpoint"] == ep2


def test_onchain_api_routes() -> None:
    client = TestClient(app)
    # Test GET /api/v1/onchain/chains
    res = client.get("/api/v1/onchain/chains")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert any(c["key"] == "sepolia" for c in data["data"])

    # Test POST /api/v1/onchain/verify with invalid address
    res = client.post("/api/v1/onchain/verify", json={"address": "bad", "chain": "sepolia"})
    assert res.status_code == 400
