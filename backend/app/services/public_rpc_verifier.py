"""Public Free EVM RPC contract and liveness verifier.

Queries 100% keyless, free public EVM RPC endpoints (publicnode, official foundation RPCs)
to verify if a given contract or deployer address is active on testnet or mainnet.
Zero commercial API cost.
"""

from __future__ import annotations

import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

logger = structlog.get_logger(__name__)

ADDRESS_REGEX = re.compile(r"^0x[a-fA-F0-9]{40}$")

SUPPORTED_CHAINS: dict[str, dict[str, Any]] = {
    "sepolia": {
        "name": "Ethereum Sepolia",
        "type": "testnet",
        "chain_id": 11155111,
        "endpoints": [
            "https://ethereum-sepolia-rpc.publicnode.com",
            "https://rpc.sepolia.org",
        ],
    },
    "arbitrum_sepolia": {
        "name": "Arbitrum Sepolia",
        "type": "testnet",
        "chain_id": 421614,
        "endpoints": [
            "https://sepolia-rollup.arbitrum.io/rpc",
            "https://arbitrum-sepolia.publicnode.com",
        ],
    },
    "base_sepolia": {
        "name": "Base Sepolia",
        "type": "testnet",
        "chain_id": 84532,
        "endpoints": [
            "https://sepolia.base.org",
            "https://base-sepolia.publicnode.com",
        ],
    },
    "optimism_sepolia": {
        "name": "Optimism Sepolia",
        "type": "testnet",
        "chain_id": 11155420,
        "endpoints": [
            "https://sepolia.optimism.io",
            "https://optimism-sepolia.publicnode.com",
        ],
    },
    "polygon_amoy": {
        "name": "Polygon Amoy",
        "type": "testnet",
        "chain_id": 80002,
        "endpoints": [
            "https://rpc-amoy.polygon.technology",
            "https://polygon-amoy.publicnode.com",
        ],
    },
    "berachain_bartio": {
        "name": "Berachain bArtio",
        "type": "testnet",
        "chain_id": 80084,
        "endpoints": [
            "https://bartio.rpc.berachain.com",
        ],
    },
    "ethereum": {
        "name": "Ethereum Mainnet",
        "type": "mainnet",
        "chain_id": 1,
        "endpoints": [
            "https://ethereum-rpc.publicnode.com",
            "https://cloudflare-eth.com",
        ],
    },
}


def is_valid_evm_address(address: str) -> bool:
    """Check if address is a valid 40-hex EVM address with 0x prefix."""
    if not address or not isinstance(address, str):
        return False
    return bool(ADDRESS_REGEX.match(address.strip()))


async def verify_contract_liveness(
    address: str,
    chain: str = "sepolia",
    timeout: float = 4.0,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Verify EVM contract bytecode and activity via free public RPCs.

    Returns structured status indicating whether the address has deployed bytecode,
    transaction count, latency, and RPC used.
    """
    clean_address = address.strip() if address else ""
    if not is_valid_evm_address(clean_address):
        return {
            "address": clean_address,
            "chain": chain,
            "is_valid": False,
            "is_contract": False,
            "deployed": False,
            "bytecode_size": 0,
            "transaction_count": 0,
            "status": "invalid_address",
            "error": "Invalid EVM address format (must be 0x followed by 40 hex characters)",
            "verified_at": datetime.now(UTC).isoformat(),
        }

    chain_key = chain.lower().strip()
    chain_info = SUPPORTED_CHAINS.get(chain_key)
    if not chain_info:
        return {
            "address": clean_address,
            "chain": chain,
            "is_valid": True,
            "is_contract": False,
            "deployed": False,
            "bytecode_size": 0,
            "transaction_count": 0,
            "status": "unsupported_chain",
            "error": f"Unsupported chain '{chain}'. Available: {list(SUPPORTED_CHAINS.keys())}",
            "verified_at": datetime.now(UTC).isoformat(),
        }

    endpoints = chain_info["endpoints"]
    last_error: str | None = None

    own_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=timeout)
        own_client = True

    try:
        for endpoint in endpoints:
            start_t = time.perf_counter()
            try:
                # 1. eth_getCode to check bytecode
                code_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getCode",
                    "params": [clean_address, "latest"],
                    "id": 1,
                }
                res = await client.post(endpoint, json=code_payload)
                if res.status_code != 200:
                    last_error = f"HTTP {res.status_code}"
                    continue

                data = res.json()
                code = str(data.get("result") or "0x")
                is_contract = len(code) > 2 and code not in ("0x", "0x0")
                bytecode_size = max(0, (len(code) - 2) // 2)

                # 2. eth_getTransactionCount to check activity/nonce
                tx_payload = {
                    "jsonrpc": "2.0",
                    "method": "eth_getTransactionCount",
                    "params": [clean_address, "latest"],
                    "id": 2,
                }
                tx_res = await client.post(endpoint, json=tx_payload)
                tx_count = 0
                if tx_res.status_code == 200:
                    tx_data = tx_res.json()
                    nonce_hex = str(tx_data.get("result") or "0x0")
                    if nonce_hex.startswith("0x"):
                        try:
                            tx_count = int(nonce_hex, 16)
                        except ValueError:
                            tx_count = 0

                latency_ms = round((time.perf_counter() - start_t) * 1000, 2)
                deployed = is_contract or tx_count > 0

                return {
                    "address": clean_address,
                    "chain": chain_key,
                    "chain_name": chain_info["name"],
                    "is_valid": True,
                    "is_contract": is_contract,
                    "deployed": deployed,
                    "bytecode_size": bytecode_size,
                    "transaction_count": tx_count,
                    "rpc_endpoint": endpoint,
                    "latency_ms": latency_ms,
                    "status": "active" if deployed else "empty",
                    "error": None,
                    "verified_at": datetime.now(UTC).isoformat(),
                }

            except Exception as e:
                last_error = str(e)
                logger.warning(
                    "public_rpc.endpoint_failed",
                    endpoint=endpoint,
                    chain=chain_key,
                    error=str(e),
                )
                continue

        # All endpoints failed
        return {
            "address": clean_address,
            "chain": chain_key,
            "chain_name": chain_info["name"],
            "is_valid": True,
            "is_contract": False,
            "deployed": False,
            "bytecode_size": 0,
            "transaction_count": 0,
            "rpc_endpoint": None,
            "status": "error",
            "error": f"All public RPC endpoints failed for {chain_key}: {last_error}",
            "verified_at": datetime.now(UTC).isoformat(),
        }

    finally:
        if own_client:
            await client.aclose()
