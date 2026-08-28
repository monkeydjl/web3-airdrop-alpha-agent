"""Etherscan On-Chain Collector.

Monitors recent Ethereum logs for high-activity token contracts and emits
RawDiscovery records. This is a lightweight heuristics source: the project
name cannot be derived directly from chain data, so we surface the contract
address as the primary identifier and let downstream normalization / merge
steps correlate it with off-chain sources (DefiLlama, Twitter, etc.).

Reference:
- DATA_SOURCE_STRATEGY.md §3. On-chain Data
- ENGINEERING_ROADMAP.md §6.2
- ADR-012-system-direction-auto-scan.md
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
import structlog

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery, RawSignal
from app.collectors.rate_limiter import TokenBucketRateLimiter
from app.config import settings
from app.utils.redact import redact

logger = structlog.get_logger(__name__)


# ERC20 Transfer event signature hash
TRANSFER_TOPIC0 = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# Well-known Ethereum contracts — high transfer volume, not early airdrop alpha
_KNOWN_NOISE_CONTRACTS = {
    "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",  # USDC
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
    "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",  # WBTC
    "0x7d1afa7b718fb893db30a3abc0cfc608aacfebb0",  # MATIC
    "0x514910771af9ca656af840dff83e8264ecf986ca",  # LINK
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984",  # UNI
    "0x95ad61b0a150d79219dcf64e1e6cc01f0b64c4ce",  # SHIB
    "0xae7ab96520de3a18e5e111b5eaab095312d7fe84",  # stETH
    "0xbe9895146f7af43049ca1c1ae358b0541ea49704",  # cbETH
    "0x7f39c581f595b53c5cb19bd0b3f8da6c935e2ca0",  # wstETH
}


class EtherscanCollector(DataCollector):
    """Etherscan 链上活跃度采集器。

    采集策略：
    1. 查询最近 N 个区块的 ERC20 Transfer 事件日志
    2. 按合约地址聚合事件数量
    3. 过滤已知稳定币/蓝筹合约，超过活跃度阈值进入候选池
    4. discovery_score 刻意压低（默认 < 分析阈值 0.3），仅作信号源
    """

    BLOCK_RANGE = 1000
    MIN_EVENTS = 50
    TOP_N = 50
    # Keep on-chain-only discoveries below default analysis threshold (0.3)
    MAX_DISCOVERY_SCORE = 0.28
    MIN_UNIQUE_RATIO = 0.05  # unique recipients / events

    def __init__(self) -> None:
        super().__init__(source_id="etherscan", source_name="Etherscan")
        self.base_url = "https://api.etherscan.io/v2/api"
        self.timeout = settings.etherscan_timeout if hasattr(settings, "etherscan_timeout") else 30
        self.retry = settings.etherscan_retry if hasattr(settings, "etherscan_retry") else 3
        self.api_key = settings.etherscan_api_key
        self.rate_limiter = TokenBucketRateLimiter("etherscan")
        self.logger = logger.bind(source_id=self.source_id)

    @property
    def source_type(self) -> str:
        return "api"

    def is_enabled(self) -> bool:
        return bool(settings.etherscan_enabled and self.api_key)

    async def collect(self) -> CollectorResult:
        """执行 Etherscan 链上日志采集。"""
        result = CollectorResult(source_id=self.source_id)
        result.started_at = datetime.now(UTC)

        try:
            latest_block = await self._fetch_latest_block()
            from_block = max(0, latest_block - self.BLOCK_RANGE)
            to_block = latest_block

            logs = await self._fetch_transfer_logs(from_block, to_block)
            self.logger.info(
                "etherscan.logs_fetched",
                from_block=from_block,
                to_block=to_block,
                log_count=len(logs),
            )

            contracts = self._aggregate_contract_activity(logs)
            candidates = self._select_candidates(contracts)
            self.logger.info(
                "etherscan.candidates",
                count=len(candidates),
            )

            for contract in candidates:
                discovery = self._build_discovery(contract)
                result.items.append(discovery)

            result.status = "success" if result.items else "partial"

        except Exception as e:
            msg = redact(str(e))
            self.logger.error("etherscan.error", error=msg)
            result.status = "error"
            result.error_message = msg

        finally:
            result.finished_at = datetime.now(UTC)

        return result

    async def health_check(self) -> dict[str, Any]:
        """检查 Etherscan API 连通性。"""
        if not self.is_enabled():
            return {"source_id": self.source_id, "status": "disabled"}
        try:
            latest = await self._fetch_latest_block()
            return {"source_id": self.source_id, "status": "healthy", "latest_block": latest}
        except Exception as e:
            return {"source_id": self.source_id, "status": "unhealthy", "error": redact(str(e))}

    async def _fetch_latest_block(self) -> int:
        """获取最新区块号。"""
        url = f"{self.base_url}?chainid=1&module=proxy&action=eth_blockNumber&apikey={self.api_key}"
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        result = data.get("result")
        if isinstance(result, str) and result.startswith("0x"):
            return int(result, 16)
        raise ValueError(f"Unexpected blockNumber response: {data}")

    async def _fetch_transfer_logs(self, from_block: int, to_block: int) -> list[dict[str, Any]]:
        """获取指定区块范围内的 ERC20 Transfer 日志。"""
        url = (
            f"{self.base_url}?chainid=1&module=logs&action=getLogs"
            f"&fromBlock={from_block}&toBlock={to_block}"
            f"&topic0={TRANSFER_TOPIC0}"
            f"&apikey={self.api_key}"
        )
        async with self.rate_limiter, httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        status = data.get("status")
        message = data.get("message", "")
        if status == "0" and "No logs found" not in message and "No records found" not in message:
            # Etherscan returns status=0 for both errors and empty results.
            # Treat messages containing "No records" / "No logs" as empty.
            raise ValueError(f"Etherscan API error: {message}")

        return data.get("result", []) or []

    def _aggregate_contract_activity(self, logs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """按合约地址聚合 Transfer 事件。"""
        contracts: dict[str, dict[str, Any]] = {}
        for log in logs:
            address = log.get("address", "").lower()
            if not address:
                continue

            if address not in contracts:
                contracts[address] = {
                    "address": address,
                    "event_count": 0,
                    "unique_to": set(),
                    "gas_used": 0,
                }

            contracts[address]["event_count"] += 1
            # topics[2] is the 'to' address for Transfer events
            topics = log.get("topics", [])
            if len(topics) >= 3:
                contracts[address]["unique_to"].add(topics[2].lower())

            gas = log.get("gasUsed") or "0x0"
            if isinstance(gas, str) and gas.startswith("0x"):
                contracts[address]["gas_used"] += int(gas, 16)

        return contracts

    def _select_candidates(self, contracts: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
        """选择高活跃度合约，排除已知蓝筹/稳定币噪声。"""
        ranked = sorted(
            contracts.values(),
            key=lambda c: c["event_count"],
            reverse=True,
        )
        candidates: list[dict[str, Any]] = []
        for c in ranked:
            address = (c.get("address") or "").lower()
            if address in _KNOWN_NOISE_CONTRACTS:
                continue
            if c["event_count"] < self.MIN_EVENTS:
                continue
            unique_n = len(c.get("unique_to") or set())
            # Reject wash-like single-recipient spam
            if unique_n < 3:
                continue
            ratio = unique_n / max(c["event_count"], 1)
            if ratio < self.MIN_UNIQUE_RATIO:
                continue
            c["unique_to_count"] = unique_n
            c.pop("unique_to", None)
            candidates.append(c)
            if len(candidates) >= self.TOP_N:
                break
        return candidates

    def _build_discovery(self, contract: dict[str, Any]) -> RawDiscovery:
        """将合约活动转换为 RawDiscovery。"""
        address = contract["address"]
        name = self._contract_name(address)
        event_count = contract["event_count"]
        unique_to_count = contract["unique_to_count"]
        gas_used = contract["gas_used"]

        discovery_score = self._calculate_discovery_score(contract)

        raw_data = {
            "address": address,
            "chain": "ethereum",
            "event_count": event_count,
            "unique_to_count": unique_to_count,
            "gas_used": gas_used,
            "block_range": self.BLOCK_RANGE,
            "signal_only": True,
        }

        signals = [
            RawSignal(
                signal_type="chain_activity",
                signal_source=self.source_id,
                signal_data={"event_count": event_count, "unique_to_count": unique_to_count},
                signal_strength=min(1.0, event_count / 1000.0),
            ),
            RawSignal(
                signal_type="gas_usage",
                signal_source=self.source_id,
                signal_data={"gas_used": gas_used},
                signal_strength=min(1.0, gas_used / 1_000_000_000.0),
            ),
        ]

        return RawDiscovery(
            source_id=self.source_id,
            raw_id=address,
            name=name,
            url=f"https://etherscan.io/address/{address}",
            # 链上活动不等于赛道；写死 "On-chain" 会让本源永远无法与他源合并
            sector=None,
            stage="mainnet",
            raw_data=raw_data,
            raw_signals=signals,
            discovery_score=discovery_score,
            discovered_at=datetime.now(UTC),
        )

    def _contract_name(self, address: str) -> str:
        """从地址生成可读名称（占位，真实场景可调用 etherscan contract/getsourcecode）。"""
        short = address[:10]
        return f"Contract {short}"

    def _calculate_discovery_score(self, contract: dict[str, Any]) -> float:
        """基于活跃度计算 discovery_score（上限压在分析阈值之下）。"""
        event_count = float(contract["event_count"])
        unique_to_count = float(contract.get("unique_to_count", 0))

        event_score = min(1.0, max(0.0, (event_count - self.MIN_EVENTS) / 1000.0))
        unique_score = min(1.0, unique_to_count / 500.0)
        raw = 0.6 * event_score + 0.4 * unique_score
        # Scale into signal-only band
        return round(min(self.MAX_DISCOVERY_SCORE, 0.08 + raw * 0.2), 3)
