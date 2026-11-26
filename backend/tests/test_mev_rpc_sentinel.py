"""Tests for MEV Protection & Private RPC Route Sentinel."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.mev_rpc_sentinel import (
    PRESET_MEV_RPC_NODES,
    benchmark_rpc_node,
    benchmark_rpc_node_live,
    list_mev_rpc_nodes,
)
from app.services.vitals import BlockedTargetError


def test_list_mev_rpc_nodes() -> None:
    nodes = list_mev_rpc_nodes()
    assert len(nodes) >= 4
    ids = [n["id"] for n in nodes]
    assert "flashbots_protect" in ids
    assert "mev_blocker" in ids

    eth_nodes = list_mev_rpc_nodes(chain_id=1)
    assert all(n["chain_id"] == 1 for n in eth_nodes)
    arb_nodes = list_mev_rpc_nodes(chain_id=42161)
    assert len(arb_nodes) >= 1
    assert arb_nodes[0]["chain_name"] == "Arbitrum One"


def test_benchmark_rpc_preset_node() -> None:
    res = benchmark_rpc_node(node_id="mev_blocker")
    assert res["status"] == "online"
    assert res["safety_rating"] == "A+"
    assert res["node_info"]["mev_refund"] is True
    assert res["node_info"]["mev_refund_pct"] == 90
    assert "Ethereum (MEVBlocker)" in res["node_info"]["network_config"]["chainName"]


def test_benchmark_rpc_custom_node() -> None:
    res = benchmark_rpc_node(custom_url="https://custom.flashbots-relay.org")
    assert res["status"] == "online"
    assert res["node_info"]["anti_sandwich"] is True
    assert res["safety_rating"] in ("A", "A+")


@pytest.mark.asyncio
async def test_benchmark_rpc_node_live_measures_rtt_and_parses_block(monkeypatch: pytest.MonkeyPatch) -> None:
    preset_before = next(n["latency_ms"] for n in PRESET_MEV_RPC_NODES if n["id"] == "mev_blocker")

    class _FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

        async def __aenter__(self) -> _FakeClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            assert url == "https://rpc.mevblocker.io"
            assert json["method"] == "eth_blockNumber"
            req = httpx.Request("POST", url)
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x14d27d0"}, request=req)

    monkeypatch.setattr("app.services.mev_rpc_sentinel.httpx.AsyncClient", _FakeClient)
    result, is_live = await benchmark_rpc_node_live(node_id="mev_blocker", allow_live=True)
    assert is_live is True
    assert result["latest_block"] == int("0x14d27d0", 16)
    assert isinstance(result["latency_ms"], float)
    # 预设全局字典不可被原地污染
    preset_after = next(n["latency_ms"] for n in PRESET_MEV_RPC_NODES if n["id"] == "mev_blocker")
    assert preset_after == preset_before


@pytest.mark.asyncio
async def test_benchmark_rpc_node_live_falls_back_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutClient:
        def __init__(self, **kwargs: object) -> None:
            del kwargs

        async def __aenter__(self) -> _TimeoutClient:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, url: str, json: dict[str, object]) -> httpx.Response:
            del json
            raise httpx.ReadTimeout("timed out", request=httpx.Request("POST", url))

    monkeypatch.setattr("app.services.mev_rpc_sentinel.httpx.AsyncClient", _TimeoutClient)
    result, is_live = await benchmark_rpc_node_live(node_id="flashbots_protect", allow_live=True)
    assert is_live is False
    assert result["latency_ms"] == 78


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_url",
    [
        "http://rpc.mevblocker.io",
        "https://localhost:8545",
        "https://127.0.0.1:8545",
        "https://169.254.169.254/latest/meta-data",
        "https://[::ffff:127.0.0.1]:8545",
    ],
)
async def test_benchmark_rpc_node_live_rejects_ssrf_custom_url(bad_url: str) -> None:
    with pytest.raises(BlockedTargetError):
        await benchmark_rpc_node_live(custom_url=bad_url, allow_live=False)


def test_mev_rpc_router_marks_real_when_live_and_rejects_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    app = create_app()
    with TestClient(app) as client:
        resp_ssrf = client.post("/api/v1/mev-rpc/benchmark", json={"custom_url": "https://127.0.0.1:8545"})
        assert resp_ssrf.status_code == 400
        assert resp_ssrf.json()["error"]["code"] == "INVALID_RPC_URL"

        async def _fake_live(
            node_id: str | None = None, custom_url: str | None = None
        ) -> tuple[dict[str, object], bool]:
            base = benchmark_rpc_node(node_id=node_id, custom_url=custom_url)
            base["latency_ms"] = 19.4
            base["latest_block"] = 21_900_001
            return base, True

        monkeypatch.setattr("app.routers.v1.mev_rpc.benchmark_rpc_node_live", _fake_live)
        resp_ok = client.post("/api/v1/mev-rpc/benchmark", json={"node_id": "mev_blocker"})
        assert resp_ok.status_code == 200
        body = resp_ok.json()
        assert body["data_quality"]["quality"] == "real"
        assert body["data"]["latency_ms"] == 19.4
        assert body["data"]["latest_block"] == 21_900_001
