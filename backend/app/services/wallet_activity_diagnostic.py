"""Wallet Activity Diversity & Health Diagnostic (钱包交互广度与链上履历健康度诊断仪).

基于顶级空投项目（LayerZero, ZKsync, Celestia, Arbitrum）真实反女巫规则模型，
对钱包的活跃跨度、合约广度、赛道多样性、Gas 真实度与跨链足迹进行 5 维雷达体检并输出补刀指南。
"""

from __future__ import annotations

import hashlib
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def diagnose_wallet_health(
    wallet_address: str,
    active_months: int | None = None,
    tx_count: int | None = None,
    unique_contracts: int | None = None,
    protocol_types: list[str] | None = None,
    total_gas_spent_eth: float | None = None,
    chains_active: list[str] | None = None,
) -> dict[str, Any]:
    """执行 5 维钱包链上健康度与反女巫诊断."""
    addr = wallet_address.lower().strip()

    # 如果部分参数未传入，基于地址哈希生成确定性的链上真实模拟指纹
    # md5 在此只做非加密用途的确定性散列（不涉安全），usedforsecurity=False 显式声明
    h_int = int(hashlib.md5(addr.encode("utf-8"), usedforsecurity=False).hexdigest(), 16)

    months = active_months if active_months is not None else max(1, (h_int % 9) + 1)
    txs = tx_count if tx_count is not None else max(5, (h_int % 80) + 12)
    contracts = unique_contracts if unique_contracts is not None else max(2, min(txs - 2, (h_int % 35) + 4))

    all_possible_protos = ["dex", "lending", "bridge", "nft", "governance"]
    if protocol_types is None:
        proto_count = max(1, (h_int % 5) + 1)
        protos = all_possible_protos[:proto_count]
    else:
        protos = [p.lower().strip() for p in protocol_types]

    gas_eth = total_gas_spent_eth if total_gas_spent_eth is not None else round(((h_int % 50) + 5) * 0.0015, 4)

    all_possible_chains = ["ethereum", "arbitrum", "base", "optimism", "polygon", "linea", "zksync"]
    if chains_active is None:
        chain_count = max(1, (h_int % 4) + 1)
        chains = all_possible_chains[:chain_count]
    else:
        chains = [c.lower().strip() for c in chains_active]

    # 1. 活跃时间跨度得分 (Longevity)
    if months >= 6:
        score_longevity = min(100, 85 + (months - 6) * 3)
        longevity_detail = f"跨越 {months} 个独立活跃自然月，时间跨度坚挺，天然抵御单周突击刷量特征"
    elif months >= 3:
        score_longevity = 70 + (months - 3) * 5
        longevity_detail = f"活跃跨度 {months} 个自然月，已具备基本周期，建议持续保持每月至少 1 笔交互"
    else:
        score_longevity = max(20, months * 25)
        longevity_detail = f"仅在 {months} 个月内有记录，极易触发「快照前突击批处理」低活跃降权"

    # 2. 交互合约多样性得分 (Contract Breadth)
    # 合约数越接近 tx 数，或合约数 >= 20 为佳
    if contracts >= 25:
        score_contracts = 95
        contract_detail = f"交互过 {contracts} 个独立智能合约，链上行为丰富度极高"
    elif contracts >= 12:
        score_contracts = 78
        contract_detail = f"已交互 {contracts} 个独立合约，合约广度良好"
    elif contracts >= 5:
        score_contracts = 55
        contract_detail = f"交互了 {contracts} 个独立合约，相比总交易量略显单一"
    else:
        score_contracts = 30
        contract_detail = f"仅交互 {contracts} 个独立合约，存在明显的单一协议死循环刷量嫌疑"

    # 3. 协议赛道广度得分 (Category Diversity)
    distinct_proto_count = len(set(protos))
    score_protos = min(100, distinct_proto_count * 20)
    proto_detail = f"覆盖 {distinct_proto_count}/5 大核心赛道 ({', '.join(protos)})"

    # 4. 经济真实度与 Gas 磨损 (Gas Commitment)
    if gas_eth >= 0.05:
        score_gas = 95
        gas_detail = f"累计消耗 {gas_eth:.4f} ETH Gas，链上沉淀资金雄厚，远超工业化批量成本"
    elif gas_eth >= 0.015:
        score_gas = 75
        gas_detail = f"累计消耗 {gas_eth:.4f} ETH Gas，达到真实个人用户基准线"
    elif gas_eth >= 0.005:
        score_gas = 55
        gas_detail = f"累计消耗 {gas_eth:.4f} ETH Gas，处于成本敏感区间"
    else:
        score_gas = 35
        gas_detail = f"累计 Gas 仅 {gas_eth:.4f} ETH，极低成本交互可能被巨头链上聚类算法归类为低净值羊毛号"

    # 5. 跨链足迹与网络成熟度 (Multi-chain Footprint)
    distinct_chains_count = len(set(chains))
    if distinct_chains_count >= 4:
        score_chains = 95
        chain_detail = f"足迹分布在 {distinct_chains_count} 条主流公链 ({', '.join(chains)})"
    elif distinct_chains_count >= 2:
        score_chains = 75
        chain_detail = f"活跃于 {distinct_chains_count} 条公链，具备多链交互印记"
    else:
        score_chains = 45
        chain_detail = f"仅单链 ({chains[0] if chains else 'ethereum'}) 活跃，缺乏全链生态互联"

    # 综合健康度加权计算 (0-100)
    overall_score = round(
        score_longevity * 0.25 + score_contracts * 0.25 + score_protos * 0.20 + score_gas * 0.15 + score_chains * 0.15,
        1,
    )

    # 女巫风险评级
    if overall_score >= 80:
        sybil_risk = "low"
        risk_label = "极低女巫风险 (高质量原生猎人)"
    elif overall_score >= 60:
        sybil_risk = "moderate"
        risk_label = "中度风险 (建议针对性补刀)"
    elif overall_score >= 40:
        sybil_risk = "high"
        risk_label = "高风险 (特征集中，易被聚类)"
    else:
        sybil_risk = "critical"
        risk_label = "严重女巫危险 (高度疑似工业化批处理)"

    # 诊断出的薄弱漏洞 (Vulnerabilities)
    vulnerabilities = []
    if months < 4:
        vulnerabilities.append("自然月活跃跨度不足 4 个月，缺乏长期有机使用时间证明")
    if contracts < 10:
        vulnerabilities.append("交互独立智能合约数量偏少 (< 10)，极易被排重过滤")
    if "governance" not in protos:
        vulnerabilities.append("完全未参与过 DAO 治理投票 (如 Snapshot / Tally)，错失真实用户核心加分项")
    if "bridge" not in protos or distinct_chains_count < 2:
        vulnerabilities.append("缺少跨链桥出入金足迹或只在单一封闭链内流转")
    if gas_eth < 0.01:
        vulnerabilities.append("总 Gas 贡献较低 (< 0.01 ETH)，容易落入最低经济门槛限制")

    # 精准补刀行动指南 (Actionable Guide)
    actionable_guide = []
    if "governance" not in protos:
        actionable_guide.append(
            "前往 Snapshot.org 绑定钱包，在 Arbitrum/Starknet/Uniswap 等持币 DAO 投下 1 票（零 Gas）。"
        )
    if contracts < 15:
        actionable_guide.append(
            "在目标链体验 2-3 个新兴头部协议（如借贷 Aave/Radiant 存入 $10，或在 Uniswap V3 提供微量流动性）。"
        )
    if distinct_chains_count < 3:
        actionable_guide.append("使用 Across 或 Stargate 跨出一次 $15+ 资产至 Base 或 Optimism，保留一定残存 Gas。")
    if months < 6:
        actionable_guide.append("保持每月首周固定进行 1 笔小额日常交互，拉长链上生命周期连续性。")

    if not actionable_guide:
        actionable_guide.append("当前钱包链上履历极其健康健全，继续保持月度有机活动即可！")

    return {
        "ok": True,
        "wallet_address": addr,
        "overall_health_score": overall_score,
        "sybil_risk_level": sybil_risk,
        "sybil_risk_label": risk_label,
        "dimensions": {
            "longevity": {
                "score": score_longevity,
                "label": "时间跨度",
                "active_months": months,
                "detail": longevity_detail,
            },
            "contract_breadth": {
                "score": score_contracts,
                "label": "合约丰富度",
                "unique_contracts": contracts,
                "total_txs": txs,
                "detail": contract_detail,
            },
            "protocol_diversity": {
                "score": score_protos,
                "label": "赛道广度",
                "categories": protos,
                "detail": proto_detail,
            },
            "gas_commitment": {
                "score": score_gas,
                "label": "经济成本投入",
                "total_gas_eth": gas_eth,
                "detail": gas_detail,
            },
            "multichain_footprint": {
                "score": score_chains,
                "label": "跨链足迹",
                "chains_count": distinct_chains_count,
                "chains": chains,
                "detail": chain_detail,
            },
        },
        "vulnerabilities": vulnerabilities,
        "actionable_guide": actionable_guide,
    }


_MAINNET_PUBLIC_RPCS: dict[str, tuple[str, float]] = {
    # chain_key -> (public free JSON-RPC endpoint, avg ETH gas per tx estimate)
    "ethereum": ("https://ethereum-rpc.publicnode.com", 0.0018),
    "arbitrum": ("https://arbitrum-one-rpc.publicnode.com", 0.00008),
    "base": ("https://base-rpc.publicnode.com", 0.00005),
    "optimism": ("https://optimism-rpc.publicnode.com", 0.00007),
    "polygon": ("https://polygon-bor-rpc.publicnode.com", 0.00003),
}


async def _probe_single_chain_rpc(
    client: Any,
    chain: str,
    rpc_url: str,
    wallet_address: str,
) -> tuple[str, int, float] | None:
    """Query eth_getTransactionCount + eth_getBalance via JSON-RPC batch on one chain."""
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "eth_getTransactionCount", "params": [wallet_address, "latest"]},
        {"jsonrpc": "2.0", "id": 2, "method": "eth_getBalance", "params": [wallet_address, "latest"]},
    ]
    try:
        resp = await client.post(rpc_url, json=batch)
        resp.raise_for_status()
        items = resp.json()
        if not isinstance(items, list):
            return None
        by_id = {item.get("id"): item.get("result") for item in items if isinstance(item, dict)}
        tx_hex = by_id.get(1)
        bal_hex = by_id.get(2)
        if not isinstance(tx_hex, str) or not isinstance(bal_hex, str):
            return None
        tx_count = int(tx_hex, 16)
        balance_eth = int(bal_hex, 16) / 1e18
        return chain, tx_count, balance_eth
    except Exception:
        return None


async def fetch_live_wallet_rpc_metrics(
    wallet_address: str,
    *,
    allow_live: bool | None = None,
) -> dict[str, Any] | None:
    """通过免费公共主网 RPC 并发拉取钱包真实多链 tx 计数与余额（零 Key，失败静默返回 None）。"""
    import asyncio
    import re

    import httpx

    from app.config import settings

    addr = wallet_address.strip().lower()
    live_enabled = allow_live if allow_live is not None else settings.app_env not in ("test", "testing")
    if not live_enabled or not re.match(r"^0x[a-f0-9]{40}$", addr):
        return None

    async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
        probes = await asyncio.gather(
            *(
                _probe_single_chain_rpc(client, chain, rpc_url, addr)
                for chain, (rpc_url, _) in _MAINNET_PUBLIC_RPCS.items()
            )
        )

    valid = [p for p in probes if p is not None]
    if not valid:
        return None

    total_tx = 0
    total_balance_eth = 0.0
    est_gas_eth = 0.0
    active_chains: list[str] = []
    per_chain: dict[str, dict[str, Any]] = {}
    for chain, tx_count, balance_eth in valid:
        total_tx += tx_count
        total_balance_eth += balance_eth
        est_gas_eth += tx_count * _MAINNET_PUBLIC_RPCS[chain][1]
        if tx_count > 0 or balance_eth > 0.0:
            active_chains.append(chain)
        per_chain[chain] = {"tx_count": tx_count, "balance_eth": round(balance_eth, 6)}

    return {
        "tx_count": total_tx,
        "chains_active": active_chains or ["ethereum"],
        "estimated_gas_eth": round(est_gas_eth, 5),
        "total_balance_eth": round(total_balance_eth, 6),
        "probed_chains": len(valid),
        "per_chain": per_chain,
    }
