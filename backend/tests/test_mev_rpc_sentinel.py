"""Tests for MEV Protection & Private RPC Route Sentinel."""

from app.services.mev_rpc_sentinel import benchmark_rpc_node, list_mev_rpc_nodes


def test_list_mev_rpc_nodes() -> None:
    nodes = list_mev_rpc_nodes()
    assert len(nodes) >= 4
    # Check flashbots and mevblocker exist
    ids = [n["id"] for n in nodes]
    assert "flashbots_protect" in ids
    assert "mev_blocker" in ids

    # Chain ID filtering
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
