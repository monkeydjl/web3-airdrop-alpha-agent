"""Unit tests for Gas Tracker Service and API."""

from app.services.gas_tracker import (
    SUPPORTED_CHAINS,
    get_all_chains_gas_summary,
    get_chain_gas_status,
)


def test_supported_chains_configuration():
    """验证所有链配置包含必要阈值与 RPC URL."""
    for chain_key, cfg in SUPPORTED_CHAINS.items():
        assert "cheap_threshold" in cfg
        assert "expensive_threshold" in cfg
        assert cfg["cheap_threshold"] < cfg["expensive_threshold"]
        assert len(cfg["rpc_urls"]) > 0


def test_get_chain_gas_status_ethereum():
    """验证以太坊主网 Gas 探查结果结构合法."""
    res = get_chain_gas_status("ethereum")
    assert res["chain"] == "ethereum"
    assert res["symbol"] == "ETH"
    assert res["gwei"] > 0.0
    assert res["status"] in ("cheap", "moderate", "expensive")
    assert "status_zh" in res


def test_get_all_chains_gas_summary():
    """验证全链概览数据包含推荐窗口与所有主流链."""
    summary = get_all_chains_gas_summary()
    assert summary["ok"] is True
    chains = summary["chains"]
    assert "ethereum" in chains
    assert "arbitrum" in chains
    assert "base" in chains
    assert "recommendations" in summary
    assert "best_weekly_windows" in summary["recommendations"]
