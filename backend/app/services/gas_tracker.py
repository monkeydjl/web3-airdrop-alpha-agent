"""Cross-Chain Real-Time Gas Tracker & Timing Predictor Service (全链 Gas 实时监控与极佳交互时段预测).

免 Key 探查主流 EVM 公链实时 Gas 价格，评估当前交互摩擦等级，并提供 7x24 小时黄金交互时段指引。
"""

import time
from typing import Any
import httpx
import structlog

logger = structlog.get_logger(__name__)

# 支持的主流链及其免 Key 公共 RPC 备用节点
SUPPORTED_CHAINS: dict[str, dict[str, Any]] = {
    "ethereum": {
        "name": "Ethereum",
        "icon": "⟠",
        "symbol": "ETH",
        "rpc_urls": [
            "https://rpc.ankr.com/eth",
            "https://cloudflare-eth.com",
            "https://eth.llamarpc.com",
        ],
        "cheap_threshold": 10.0,
        "expensive_threshold": 22.0,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 150000,
    },
    "arbitrum": {
        "name": "Arbitrum One",
        "icon": "🔷",
        "symbol": "ETH",
        "rpc_urls": [
            "https://arb1.arbitrum.io/rpc",
            "https://arbitrum.llamarpc.com",
        ],
        "cheap_threshold": 0.05,
        "expensive_threshold": 0.20,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 120000,
    },
    "base": {
        "name": "Base",
        "icon": "🔵",
        "symbol": "ETH",
        "rpc_urls": [
            "https://mainnet.base.org",
            "https://base.llamarpc.com",
        ],
        "cheap_threshold": 0.03,
        "expensive_threshold": 0.15,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 120000,
    },
    "optimism": {
        "name": "Optimism",
        "icon": "🔴",
        "symbol": "ETH",
        "rpc_urls": [
            "https://mainnet.optimism.io",
            "https://optimism.llamarpc.com",
        ],
        "cheap_threshold": 0.04,
        "expensive_threshold": 0.18,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 120000,
    },
    "polygon": {
        "name": "Polygon PoS",
        "icon": "💜",
        "symbol": "MATIC",
        "rpc_urls": [
            "https://polygon-rpc.com",
            "https://polygon.llamarpc.com",
        ],
        "cheap_threshold": 30.0,
        "expensive_threshold": 80.0,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 130000,
    },
    "bsc": {
        "name": "BNB Chain",
        "icon": "🟡",
        "symbol": "BNB",
        "rpc_urls": [
            "https://binance.llamarpc.com",
            "https://bsc-dataseed.binance.org",
        ],
        "cheap_threshold": 1.5,
        "expensive_threshold": 3.5,
        "sample_tx_gas": 21000,
        "sample_swap_gas": 120000,
    },
}

# 内存缓存，避免频繁穿透公共 RPC (TTL 15s)
_GAS_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
CACHE_TTL_SECONDS = 15.0


def _fetch_rpc_gas_price(chain_key: str) -> float | None:
    """调用公共 RPC 获取当前 gasPrice (以 Gwei 为单位)."""
    cfg = SUPPORTED_CHAINS.get(chain_key)
    if not cfg:
        return None

    for rpc_url in cfg["rpc_urls"]:
        try:
            payload = {
                "jsonrpc": "2.0",
                "method": "eth_gasPrice",
                "params": [],
                "id": 1,
            }
            with httpx.Client(timeout=3.0) as client:
                resp = client.post(rpc_url, json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    hex_val = data.get("result")
                    if hex_val and isinstance(hex_val, str) and hex_val.startswith("0x"):
                        wei = int(hex_val, 16)
                        gwei = wei / 1e9
                        return round(gwei, 3)
        except Exception as e:
            logger.debug("gas_tracker.rpc_probe_failed", chain=chain_key, rpc=rpc_url, error=str(e))
            continue

    return None


def get_chain_gas_status(chain_key: str, force_refresh: bool = False) -> dict[str, Any]:
    """获取指定链的实时 Gas 详情与评级."""
    now = time.time()
    if not force_refresh and chain_key in _GAS_CACHE:
        cached_time, cached_val = _GAS_CACHE[chain_key]
        if now - cached_time < CACHE_TTL_SECONDS:
            return cached_val

    cfg = SUPPORTED_CHAINS.get(chain_key)
    if not cfg:
        return {"ok": False, "error": f"Unsupported chain: {chain_key}"}

    gwei = _fetch_rpc_gas_price(chain_key)

    # 离线退化默认估计值（防止公共 RPC 偶发超时）
    if gwei is None:
        fallback_gwei = {
            "ethereum": 8.5,
            "arbitrum": 0.08,
            "base": 0.04,
            "optimism": 0.05,
            "polygon": 35.0,
            "bsc": 1.2,
        }.get(chain_key, 10.0)
        gwei = fallback_gwei
        is_fallback = True
    else:
        is_fallback = False

    cheap_thr = cfg["cheap_threshold"]
    exp_thr = cfg["expensive_threshold"]

    if gwei <= cheap_thr:
        status = "cheap"
        status_zh = "极佳 (极低磨损)"
        level_color = "emerald"
    elif gwei <= exp_thr:
        status = "moderate"
        status_zh = "适中 (常规费率)"
        level_color = "amber"
    else:
        status = "expensive"
        status_zh = "拥堵 (高额磨损)"
        level_color = "rose"

    result = {
        "chain": chain_key,
        "name": cfg["name"],
        "icon": cfg["icon"],
        "symbol": cfg["symbol"],
        "gwei": gwei,
        "status": status,
        "status_zh": status_zh,
        "level_color": level_color,
        "is_fallback": is_fallback,
        "updated_at": int(now),
    }

    _GAS_CACHE[chain_key] = (now, result)
    return result


def get_all_chains_gas_summary() -> dict[str, Any]:
    """获取所有支持链的实时 Gas 概览与黄金时段预测."""
    chains_data = {}
    eth_status = "cheap"

    for chain_key in SUPPORTED_CHAINS.keys():
        status_data = get_chain_gas_status(chain_key)
        chains_data[chain_key] = status_data
        if chain_key == "ethereum":
            eth_status = status_data["status"]

    # 7x24 小时黄金交互时段规律总结
    recommendations = {
        "current_recommendation": (
            "当前主网费率处于极佳低谷区间，极其适合执行多钱包批量转账、质押与合约部署！"
            if eth_status == "cheap"
            else (
                "当前费率处于常规适中水平，常规交互无压力，可正常进行日常打卡与测试网任务。"
                if eth_status == "moderate"
                else "当前主网处于拥堵高位，建议暂缓大额主网交互，优先进行 L2/测试网零摩擦任务！"
            )
        ),
        "best_weekly_windows": [
            {"period": "周六至周日全天 (UTC)", "savings": "省约 45%~65% Gas", "desc": "美欧机构休息，链上活动低谷"},
            {"period": "工作日 UTC 01:00 - 06:00 (北京时间 09:00 - 14:00)", "savings": "省约 30%~50% Gas", "desc": "美洲交易下线，亚洲盘平稳期"},
        ],
        "high_friction_alert": "工作日 UTC 14:00 - 18:00 (美股开盘与欧美主流重叠期)，费率常呈突发脉冲式拉升，应避免批量密集交互。",
    }

    return {
        "ok": True,
        "chains": chains_data,
        "recommendations": recommendations,
        "timestamp": int(time.time()),
    }
