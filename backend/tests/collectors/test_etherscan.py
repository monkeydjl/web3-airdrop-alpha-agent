"""Tests for the Etherscan on-chain collector."""

import pytest
import respx
from httpx import Response

from app.collectors.etherscan import EtherscanCollector
from app.config import settings


@pytest.fixture
def etherscan_enabled(monkeypatch):
    """启用 Etherscan 并配置测试 API key。"""
    monkeypatch.setattr(settings, "etherscan_enabled", True)
    monkeypatch.setattr(settings, "etherscan_api_key", "test_api_key")


class TestEtherscanCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        """etherscan_enabled=false 时禁用。"""
        monkeypatch.setattr(settings, "etherscan_enabled", False)
        monkeypatch.setattr(settings, "etherscan_api_key", "test_api_key")
        collector = EtherscanCollector()
        assert not collector.is_enabled()

    def test_disabled_without_key(self, monkeypatch) -> None:
        """无 API key 时禁用。"""
        monkeypatch.setattr(settings, "etherscan_enabled", True)
        monkeypatch.setattr(settings, "etherscan_api_key", "")
        collector = EtherscanCollector()
        assert not collector.is_enabled()

    @respx.mock
    async def test_collect_empty_logs(self, etherscan_enabled) -> None:
        """空日志返回 partial 状态。"""
        route = respx.get(
            "https://api.etherscan.io/v2/api",
        )
        route.side_effect = [
            Response(200, json={"result": "0x10"}),  # latest block = 16
            Response(200, json={"status": "0", "message": "No records found", "result": []}),
        ]

        collector = EtherscanCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []
        assert result.error_message is None

    @respx.mock
    async def test_collect_high_activity_contract(self, etherscan_enabled) -> None:
        """高活跃度合约被识别为候选项目。"""
        logs = []
        base_address = f"0x{0:040d}"
        for i in range(60):
            logs.append(
                {
                    "address": base_address,
                    "topics": [
                        "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef",
                        "0x" + "0" * 64,
                        f"0x{i + 1:064x}",
                    ],
                    "gasUsed": "0x5208",
                }
            )

        route = respx.get("https://api.etherscan.io/v2/api")
        route.side_effect = [
            Response(200, json={"result": "0x10"}),  # latest block
            Response(200, json={"status": "1", "message": "OK", "result": logs}),
        ]

        collector = EtherscanCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.name.startswith("Contract 0x")
        assert discovery.sector == "On-chain"
        assert 0 <= discovery.discovery_score <= 0.28

    def test_known_stablecoins_filtered(self, etherscan_enabled) -> None:
        """USDT/USDC/WETH 等高噪声合约不进入候选。"""
        collector = EtherscanCollector()
        contracts = {
            "0xdac17f958d2ee523a2206206994597c13d831ec7": {
                "address": "0xdac17f958d2ee523a2206206994597c13d831ec7",
                "event_count": 500,
                "unique_to": {f"0x{i:064x}" for i in range(50)},
                "gas_used": 1000,
            },
            "0xabc0000000000000000000000000000000000001": {
                "address": "0xabc0000000000000000000000000000000000001",
                "event_count": 80,
                "unique_to": {f"0x{i:064x}" for i in range(20)},
                "gas_used": 1000,
            },
        }
        candidates = collector._select_candidates(contracts)
        addrs = {c["address"] for c in candidates}
        assert "0xdac17f958d2ee523a2206206994597c13d831ec7" not in addrs
        assert "0xabc0000000000000000000000000000000000001" in addrs

    @respx.mock
    async def test_collect_api_error(self, etherscan_enabled) -> None:
        """API 返回错误时标记为 error。"""
        route = respx.get("https://api.etherscan.io/v2/api")
        route.side_effect = [
            Response(200, json={"result": "0x10"}),
            Response(200, json={"status": "0", "message": "Invalid API Key", "result": []}),
        ]

        collector = EtherscanCollector()
        result = await collector.collect()
        assert result.status == "error"
        assert result.error_message is not None

    @respx.mock
    async def test_health_check(self, etherscan_enabled) -> None:
        """健康检查返回最新区块。"""
        route = respx.get("https://api.etherscan.io/v2/api")
        route.return_value = Response(200, json={"result": "0x14"})  # 20

        collector = EtherscanCollector()
        health = await collector.health_check()
        assert health["status"] == "healthy"
        assert health["latest_block"] == 20
