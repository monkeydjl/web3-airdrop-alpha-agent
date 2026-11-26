"""Cross-Chain Bridge & Gas Route Optimizer (跨链路由与低磨损资金规划服务).

聚合主流跨链桥方案（Across, Stargate, Hop, Orbiter, Celer, 官方 Rollup 桥），
多链（Ethereum, Arbitrum, Base, Optimism, Linea, Scroll, zkSync Era, Blast）费率实时比对，
提供极致省钱、极速到账与防女巫分批资金归集规划。
"""

from __future__ import annotations

from typing import Any

SUPPORTED_CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {"name": "Ethereum L1", "type": "l1", "avg_gas_usd": 3.80},
    "arbitrum": {"name": "Arbitrum One", "type": "l2_rollup", "avg_gas_usd": 0.03},
    "base": {"name": "Base", "type": "l2_rollup", "avg_gas_usd": 0.02},
    "optimism": {"name": "OP Mainnet", "type": "l2_rollup", "avg_gas_usd": 0.03},
    "polygon": {"name": "Polygon PoS", "type": "sidechain", "avg_gas_usd": 0.01},
    "linea": {"name": "Linea", "type": "l2_zk", "avg_gas_usd": 0.04},
    "scroll": {"name": "Scroll", "type": "l2_zk", "avg_gas_usd": 0.05},
    "zksync": {"name": "zkSync Era", "type": "l2_zk", "avg_gas_usd": 0.04},
    "blast": {"name": "Blast", "type": "l2_rollup", "avg_gas_usd": 0.03},
}

SUPPORTED_PROTOCOLS: list[dict[str, Any]] = [
    {
        "id": "across",
        "name": "Across Protocol",
        "type": "intent_based",
        "security_score": "A+",
        "url": "https://across.to/",
        "base_fee_pct": 0.0004,  # 0.04%
        "min_fee_usd": 0.35,
        "avg_time_min": 1.5,
    },
    {
        "id": "stargate",
        "name": "Stargate (LayerZero)",
        "type": "liquidity_pool",
        "security_score": "A",
        "url": "https://stargate.finance/",
        "base_fee_pct": 0.0006,  # 0.06%
        "min_fee_usd": 0.60,
        "avg_time_min": 2.5,
    },
    {
        "id": "orbiter",
        "name": "Orbiter Finance",
        "type": "maker_rollup",
        "security_score": "A",
        "url": "https://www.orbiter.finance/",
        "base_fee_pct": 0.0008,
        "min_fee_usd": 0.80,
        "avg_time_min": 1.0,
    },
    {
        "id": "hop",
        "name": "Hop Protocol",
        "type": "amm_bridge",
        "security_score": "B+",
        "url": "https://hop.exchange/",
        "base_fee_pct": 0.0010,
        "min_fee_usd": 0.90,
        "avg_time_min": 3.0,
    },
    {
        "id": "celer",
        "name": "Celer cBridge",
        "type": "state_guardian",
        "security_score": "A-",
        "url": "https://cbridge.celer.network/",
        "base_fee_pct": 0.0007,
        "min_fee_usd": 0.70,
        "avg_time_min": 4.0,
    },
    {
        "id": "canonical",
        "name": "官方 Rollup 桥 (Canonical)",
        "type": "native_rollup",
        "security_score": "A++",
        "url": "https://bridge.arbitrum.io/",
        "base_fee_pct": 0.0,
        "min_fee_usd": 0.0,
        "avg_time_min": 15.0,  # 充值 15min，但提回 L1 需 7 天挑战期
    },
]


def get_supported_bridge_chains() -> list[dict[str, Any]]:
    """返回支持跨链规划的主流区块链与 Gas 特征."""
    return [
        {
            "id": k,
            "name": v["name"],
            "type": v["type"],
            "avg_gas_usd": v["avg_gas_usd"],
        }
        for k, v in SUPPORTED_CHAINS.items()
    ]


def calculate_bridge_routes(
    source_chain: str,
    target_chain: str,
    asset: str = "ETH",
    amount: float = 1.0,
) -> dict[str, Any]:
    """计算跨链路由方案对比并给出极佳路径."""
    src = source_chain.lower().strip()
    dst = target_chain.lower().strip()

    if src not in SUPPORTED_CHAINS:
        src = "arbitrum"
    if dst not in SUPPORTED_CHAINS:
        dst = "base"

    token_upper = asset.upper().strip()
    # 模拟估算基础汇率 (ETH $2600, USDC $1.0)
    token_price_usd = 2600.0 if "ETH" in token_upper else 1.0
    transfer_value_usd = max(1.0, amount * token_price_usd)

    src_gas = SUPPORTED_CHAINS[src]["avg_gas_usd"]
    dst_gas = SUPPORTED_CHAINS[dst]["avg_gas_usd"]

    routes = []
    is_l1_bridge = src == "ethereum" or dst == "ethereum"

    for proto in SUPPORTED_PROTOCOLS:
        # 如果是官方桥，且并非以太坊直连 L2，则不可用
        if proto["id"] == "canonical" and not is_l1_bridge:
            continue

        fee_pct_cost = transfer_value_usd * proto["base_fee_pct"]
        bridge_fee = max(proto["min_fee_usd"], fee_pct_cost)
        total_gas = src_gas + (dst_gas * 1.5 if is_l1_bridge else dst_gas)

        # 官方桥 L2 跨回 L1 需 7 天
        duration = proto["avg_time_min"]
        duration_human = f"{duration} 分钟"
        if proto["id"] == "canonical" and src != "ethereum":
            duration_human = "7 天 (挑战期)"

        total_cost_usd = round(bridge_fee + total_gas, 2)

        routes.append(
            {
                "protocol_id": proto["id"],
                "protocol_name": proto["name"],
                "type": proto["type"],
                "security_score": proto["security_score"],
                "url": proto["url"],
                "bridge_fee_usd": round(bridge_fee, 2),
                "gas_cost_usd": round(total_gas, 2),
                "total_cost_usd": total_cost_usd,
                "duration_min": duration,
                "duration_human": duration_human,
                "token": token_upper,
                "amount": amount,
            }
        )

    # 排序并找出最佳路线
    routes.sort(key=lambda r: r["total_cost_usd"])
    cheapest_route = routes[0] if routes else None

    # 最快路线（排除 canonical）
    fast_candidates = [r for r in routes if r["protocol_id"] != "canonical"]
    fastest_route = min(fast_candidates, key=lambda r: r["duration_min"]) if fast_candidates else cheapest_route

    # 计算相比直接使用以太坊主网转账/官方桥节省的资金
    baseline_cost = max(4.5, transfer_value_usd * 0.002 + 8.5 if is_l1_bridge else 2.5)
    saved_usd = max(0.0, round(baseline_cost - (cheapest_route["total_cost_usd"] if cheapest_route else 0), 2))
    savings_pct = min(92, max(45, int((saved_usd / baseline_cost) * 100)))

    # 防女巫分散资金归集策略 (Sybil-Safe Recommendations)
    sybil_tips = [
        f"打散转账金额：每地址随机分配 {round(amount * 0.94, 4)} ~ {round(amount * 1.06, 4)} {token_upper}，切勿整数一刀切。",
        "时间窗口抖动：各钱包跨链交互间隔建议在 15~60 分钟内随机分布，规避同块并发关联。",
        f"终点沉淀储备：在 {SUPPORTED_CHAINS[dst]['name']} 务必沉淀至少 0.005 ETH 基础 Gas 余额，切忌转入后立刻全部提空。",
        "隔离出入金通道：避免从同一交易所或单一中心化地址分发至所有账号，建议通过不同 L2 或子账号混流。",
    ]

    return {
        "ok": True,
        "source_chain": src,
        "source_chain_name": SUPPORTED_CHAINS[src]["name"],
        "target_chain": dst,
        "target_chain_name": SUPPORTED_CHAINS[dst]["name"],
        "token": token_upper,
        "amount": amount,
        "transfer_value_usd": round(transfer_value_usd, 2),
        "routes": routes,
        "cheapest_route": cheapest_route,
        "fastest_route": fastest_route,
        "estimated_savings_usd": saved_usd,
        "savings_percentage": savings_pct,
        "sybil_safe_tips": sybil_tips,
    }


_LIFI_CHAIN_IDS: dict[str, int] = {
    "ethereum": 1,
    "arbitrum": 42161,
    "base": 8453,
    "optimism": 10,
    "polygon": 137,
    "linea": 59144,
    "scroll": 534352,
    "zksync": 324,
    "blast": 81457,
}
_LIFI_QUOTE_URL = "https://li.quest/v1/quote"
# LI.FI 公开报价仅需占位 EVM 地址用于估算 Gas/路径，不会发起任何签名或交易
_LIFI_QUOTE_DUMMY_ADDR = "0x000000000000000000000000000000000000dEaD"


async def calculate_bridge_routes_live(
    source_chain: str,
    target_chain: str,
    asset: str = "ETH",
    amount: float = 1.0,
    *,
    allow_live: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """优先向 LI.FI 公开报价 API 获取真实跨链路由与费用；失败/离线时回退静态估算。"""
    from app.collectors.base import safe_collector_client
    from app.config import settings

    fallback = calculate_bridge_routes(
        source_chain=source_chain,
        target_chain=target_chain,
        asset=asset,
        amount=amount,
    )
    live_enabled = allow_live if allow_live is not None else settings.app_env not in ("test", "testing")
    src = source_chain.lower().strip()
    dst = target_chain.lower().strip()
    if not live_enabled or src == dst or src not in _LIFI_CHAIN_IDS or dst not in _LIFI_CHAIN_IDS:
        return fallback, False

    token_upper = asset.upper().strip()
    decimals = 6 if "USD" in token_upper else 18
    from_amount_wei = str(max(1, int(amount * (10**decimals))))

    try:
        async with safe_collector_client(timeout=4.5) as client:
            resp = await client.get(
                _LIFI_QUOTE_URL,
                params={
                    "fromChain": str(_LIFI_CHAIN_IDS[src]),
                    "toChain": str(_LIFI_CHAIN_IDS[dst]),
                    "fromToken": token_upper,
                    "toToken": token_upper,
                    "fromAmount": from_amount_wei,
                    "fromAddress": _LIFI_QUOTE_DUMMY_ADDR,
                },
            )
            resp.raise_for_status()
            payload = resp.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("estimate"), dict):
            return fallback, False

        est = payload["estimate"]
        raw_tool_details = payload.get("toolDetails")
        tool_details: dict[str, Any] = raw_tool_details if isinstance(raw_tool_details, dict) else {}
        tool_key = str(payload.get("tool") or tool_details.get("key") or "lifi")
        tool_name = str(tool_details.get("name") or tool_key)

        gas_costs = est.get("gasCosts") if isinstance(est.get("gasCosts"), list) else []
        fee_costs = est.get("feeCosts") if isinstance(est.get("feeCosts"), list) else []
        gas_usd = round(sum(float(g.get("amountUSD") or 0.0) for g in gas_costs if isinstance(g, dict)), 2)
        fee_usd = round(sum(float(f.get("amountUSD") or 0.0) for f in fee_costs if isinstance(f, dict)), 2)
        total_cost_usd = round(gas_usd + fee_usd, 2)
        exec_seconds = float(est.get("executionDuration") or 90.0)
        duration_min = round(max(0.2, exec_seconds / 60.0), 1)
        from_usd = float(est.get("fromAmountUSD") or fallback["transfer_value_usd"])

        live_route = {
            "protocol_id": tool_key,
            "protocol_name": f"{tool_name} (LI.FI 实时报价)",
            "type": "lifi_aggregated_live",
            "security_score": "A+",
            "url": "https://jumper.exchange/",
            "bridge_fee_usd": fee_usd,
            "gas_cost_usd": gas_usd,
            "total_cost_usd": total_cost_usd,
            "duration_min": duration_min,
            "duration_human": f"{duration_min} 分钟",
            "token": token_upper,
            "amount": amount,
            "is_live": True,
        }

        merged_routes = [live_route, *[r for r in fallback["routes"] if r["protocol_id"] != tool_key]]
        baseline_cost = max(4.5, from_usd * 0.002 + 8.5 if (src == "ethereum" or dst == "ethereum") else 2.5)
        saved_usd = max(0.0, round(baseline_cost - total_cost_usd, 2))
        savings_pct = min(95, max(0, int((saved_usd / baseline_cost) * 100))) if baseline_cost > 0 else 0

        return (
            {
                **fallback,
                "transfer_value_usd": round(from_usd, 2),
                "routes": merged_routes,
                "cheapest_route": live_route,
                "fastest_route": min(merged_routes, key=lambda r: r["duration_min"]),
                "estimated_savings_usd": saved_usd,
                "savings_percentage": savings_pct,
                "data_source": "lifi_live",
            },
            True,
        )
    except Exception:
        return fallback, False
