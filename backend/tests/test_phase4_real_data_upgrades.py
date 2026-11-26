"""Phase 4 regression tests: real live-data upgrades for security sentinel, bridge optimizer, and wallet diagnostic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db


def _setup_isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    db_file = tmp_path / name
    monkeypatch.setattr(settings, "db_path", str(db_file))
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(settings, "db_backend", "sqlite")
    monkeypatch.setattr(settings, "scheduler_enabled", False)
    monkeypatch.setattr(settings, "collection_scheduler_enabled", False)
    init_db()


class TestPhase4RealDataUpgrades:
    """Verify GoPlus Security, LI.FI Bridge, and Multi-chain Public RPC upgrades with honest data_quality markers."""

    def test_domain_allowlist_includes_goplus_and_lifi(self) -> None:
        from app.utils.domain_allowlist import is_url_allowed

        assert is_url_allowed("https://api.gopluslabs.io/api/v1/approval_security/1") is True
        assert is_url_allowed("https://li.quest/v1/quote") is True

    @respx.mock
    @pytest.mark.asyncio
    async def test_security_approvals_live_and_fallback(self) -> None:
        from app.services.security_sentinel import scan_token_approvals_live

        wallet = "0x1111111111111111111111111111111111111111"
        respx.get("https://api.gopluslabs.io/api/v1/approval_security/1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 1,
                    "result": [
                        {
                            "token_symbol": "USDT",
                            "approved_list": [
                                {
                                    "approved_contract": "0xbad0000000000000000000000000000000000bad",
                                    "approved_amount": "Unlimited",
                                    "malicious_address": 1,
                                    "address_info": {"contract_name": "EvilDrainer", "is_open_source": 0},
                                }
                            ],
                        }
                    ],
                },
            )
        )
        data, is_live = await scan_token_approvals_live(wallet, chain_id="1", allow_live=True)
        assert is_live is True
        assert data["data_source"] == "goplus_live"
        assert data["unlimited_allowances_count"] == 1
        assert data["unverified_spenders_count"] == 1
        assert data["approvals"][0]["token"] == "USDT"
        assert data["approvals"][0]["risk_tier"] == "high"
        assert data["security_score"] <= 60

        # Offline/error gracefully falls back to simulated sample
        respx.get("https://api.gopluslabs.io/api/v1/approval_security/1").mock(
            side_effect=httpx.ConnectTimeout("timeout")
        )
        fb_data, fb_live = await scan_token_approvals_live(wallet, chain_id="1", allow_live=True)
        assert fb_live is False
        assert "data_source" not in fb_data

    @respx.mock
    @pytest.mark.asyncio
    async def test_security_poison_tokens_live_clean_and_flagged(self) -> None:
        from app.services.security_sentinel import scan_dust_poison_tokens_live

        wallet = "0x2222222222222222222222222222222222222222"
        respx.get(f"https://api.gopluslabs.io/api/v1/address_security/{wallet}").mock(
            return_value=httpx.Response(
                200,
                json={
                    "code": 1,
                    "result": {"phishing_activities": "1", "stealing_attack": "0", "fake_token": "0"},
                },
            )
        )
        flagged, is_live = await scan_dust_poison_tokens_live(wallet, chain_id="1", allow_live=True)
        assert is_live is True
        assert flagged["poison_tokens_detected"] == 1
        assert flagged["poison_tokens"][0]["token_symbol"] == "PHISHING_ACTIVITIES"

        respx.get(f"https://api.gopluslabs.io/api/v1/address_security/{wallet}").mock(
            return_value=httpx.Response(200, json={"code": 1, "result": {"phishing_activities": "0"}})
        )
        clean, clean_live = await scan_dust_poison_tokens_live(wallet, chain_id="1", allow_live=True)
        assert clean_live is True
        assert clean["poison_tokens_detected"] == 0

    @respx.mock
    @pytest.mark.asyncio
    async def test_bridge_optimizer_lifi_live_and_fallback(self) -> None:
        from app.services.bridge_optimizer import calculate_bridge_routes_live

        respx.get("https://li.quest/v1/quote").mock(
            return_value=httpx.Response(
                200,
                json={
                    "tool": "across",
                    "toolDetails": {"key": "across", "name": "Across V3"},
                    "estimate": {
                        "fromAmountUSD": "1300.0",
                        "executionDuration": 45,
                        "gasCosts": [{"amountUSD": "0.12"}],
                        "feeCosts": [{"amountUSD": "0.38"}],
                    },
                },
            )
        )
        data, is_live = await calculate_bridge_routes_live("arbitrum", "base", "ETH", 0.5, allow_live=True)
        assert is_live is True
        assert data["data_source"] == "lifi_live"
        assert data["cheapest_route"]["is_live"] is True
        assert data["cheapest_route"]["total_cost_usd"] == 0.50
        assert data["cheapest_route"]["duration_min"] == 0.8

        respx.get("https://li.quest/v1/quote").mock(return_value=httpx.Response(503))
        fb_data, fb_live = await calculate_bridge_routes_live("arbitrum", "base", "ETH", 0.5, allow_live=True)
        assert fb_live is False
        assert "data_source" not in fb_data

    @respx.mock
    @pytest.mark.asyncio
    async def test_wallet_diagnostic_live_rpc_and_api_quality_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.main import create_app
        from app.services.wallet_activity_diagnostic import _MAINNET_PUBLIC_RPCS, fetch_live_wallet_rpc_metrics

        wallet = "0x3333333333333333333333333333333333333333"
        for chain, (rpc_url, _) in _MAINNET_PUBLIC_RPCS.items():
            tx_hex = "0x14" if chain in ("ethereum", "arbitrum") else "0x0"
            bal_hex = "0xde0b6b3a7640000" if chain == "ethereum" else "0x0"  # 1 ETH
            respx.post(rpc_url).mock(
                return_value=httpx.Response(
                    200,
                    json=[
                        {"jsonrpc": "2.0", "id": 1, "result": tx_hex},
                        {"jsonrpc": "2.0", "id": 2, "result": bal_hex},
                    ],
                )
            )

        metrics = await fetch_live_wallet_rpc_metrics(wallet, allow_live=True)
        assert metrics is not None
        assert metrics["tx_count"] == 40
        assert set(metrics["chains_active"]) == {"ethereum", "arbitrum"}
        assert metrics["total_balance_eth"] == pytest.approx(1.0, abs=1e-6)

        # Verify router marks quality == "real" when live RPC + remaining user params cover all dimensions
        _setup_isolated_db(tmp_path, monkeypatch, "p4_diag.db")
        monkeypatch.setattr(settings, "app_env", "development")

        async def _fake_live(addr: str) -> dict[str, Any]:
            return {
                "tx_count": 40,
                "chains_active": ["ethereum", "arbitrum"],
                "estimated_gas_eth": 0.0376,
                "total_balance_eth": 1.0,
                "probed_chains": 5,
                "per_chain": {},
            }

        monkeypatch.setattr("app.routers.v1.diagnostic.fetch_live_wallet_rpc_metrics", _fake_live)
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/diagnostic/wallet",
                json={
                    "wallet_address": wallet,
                    "active_months": 8,
                    "unique_contracts": 18,
                    "protocol_types": ["dex", "bridge", "governance"],
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["data_quality"]["quality"] == "real"
            assert body["dimensions"]["contract_breadth"]["total_txs"] == 40
            assert body["onchain_rpc_snapshot"]["total_balance_eth"] == 1.0
