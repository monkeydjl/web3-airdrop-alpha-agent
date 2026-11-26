"""MEV Protection & Private RPC Route Sentinel (智能防夹与私有 RPC 路由节点探测服务).

为用户在领取大额空投、进行 DEX Swap、流动性添加及高价值交易时提供防三明治夹子机器人（Sandwich Attack）、
抢跑（Front-running）保护，以及搜索者套利反跑现金返还（MEV Rebate）与节点延迟连通性评测。
支持 1-Click 生成导入 MetaMask / Rabby 钱包的标准 RPC 网络参数。
"""

from __future__ import annotations

import ipaddress
import time
from typing import Any

import httpx
import structlog

from app.config import settings
from app.services.vitals import (
    BlockedTargetError,
    _build_pinned_transport,
    _is_safe_public_ip,
    _reject_non_public_target,
)
from app.utils.redact import redact

logger = structlog.get_logger(__name__)

_RPC_PROBE_TIMEOUT_SECONDS = 3.5

# 主流经过实战验证的防 MEV 私有 RPC 节点库
PRESET_MEV_RPC_NODES: list[dict[str, Any]] = [
    {
        "id": "flashbots_protect",
        "name": "Flashbots Protect",
        "chain_id": 1,
        "chain_name": "Ethereum Mainnet",
        "rpc_url": "https://rpc.flashbots.net",
        "fast_rpc_url": "https://rpc.flashbots.net/fast",
        "website": "https://flashbots.net",
        "anti_sandwich": True,
        "anti_frontrunning": True,
        "mev_refund": True,
        "mev_refund_pct": 50,
        "zero_gas_on_failure": True,
        "trust_score": 98,
        "latency_ms": 78,
        "features": ["Builders直达", "失败不扣Gas", "50%回跑套利返还", "快速模式可选"],
        "setup_guide": "向 Flashbots 验证者直接提交 Bundle，彻底绕开公开 Mempool，完全规避 Uniswap 大额滑点被夹。",
        "network_config": {
            "chainId": "0x1",
            "chainName": "Ethereum (Flashbots Protect)",
            "rpcUrls": ["https://rpc.flashbots.net"],
            "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
            "blockExplorerUrls": ["https://etherscan.io"],
        },
    },
    {
        "id": "mev_blocker",
        "name": "MEVBlocker (CoW DAO / Beaver)",
        "chain_id": 1,
        "chain_name": "Ethereum Mainnet",
        "rpc_url": "https://rpc.mevblocker.io",
        "fast_rpc_url": "https://rpc.mevblocker.io/fast",
        "website": "https://mevblocker.io",
        "anti_sandwich": True,
        "anti_frontrunning": True,
        "mev_refund": True,
        "mev_refund_pct": 90,
        "zero_gas_on_failure": True,
        "trust_score": 99,
        "latency_ms": 65,
        "features": ["90%搜索者利润返还", "极速出块", "防夹拦截", "全网主流DEX默认集成"],
        "setup_guide": "由 CoW Swap, Beaver, Agave 联合推出的公共防护层，为普通用户返还多达 90% 的回跑 (Backrunning) 获利。",
        "network_config": {
            "chainId": "0x1",
            "chainName": "Ethereum (MEVBlocker)",
            "rpcUrls": ["https://rpc.mevblocker.io"],
            "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
            "blockExplorerUrls": ["https://etherscan.io"],
        },
    },
    {
        "id": "securerpc",
        "name": "SecureRPC (Manifold Finance)",
        "chain_id": 1,
        "chain_name": "Ethereum Mainnet",
        "rpc_url": "https://api.securerpc.com/v1",
        "fast_rpc_url": "https://api.securerpc.com/v1",
        "website": "https://securerpc.com",
        "anti_sandwich": True,
        "anti_frontrunning": True,
        "mev_refund": False,
        "mev_refund_pct": 0,
        "zero_gas_on_failure": True,
        "trust_score": 92,
        "latency_ms": 82,
        "features": ["高频量化专线", "私有中继", "交易完全私密"],
        "setup_guide": "针对机构和巨鲸的高并发低延迟私有交易专线，全面阻断 Mempool 侦测扫描。",
        "network_config": {
            "chainId": "0x1",
            "chainName": "Ethereum (SecureRPC)",
            "rpcUrls": ["https://api.securerpc.com/v1"],
            "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
            "blockExplorerUrls": ["https://etherscan.io"],
        },
    },
    {
        "id": "arbitrum_private",
        "name": "Arbitrum One (Sequencer Direct)",
        "chain_id": 42161,
        "chain_name": "Arbitrum One",
        "rpc_url": "https://arb1.arbitrum.io/rpc",
        "fast_rpc_url": "https://arb1.arbitrum.io/rpc",
        "website": "https://arbitrum.io",
        "anti_sandwich": True,
        "anti_frontrunning": True,
        "mev_refund": False,
        "mev_refund_pct": 0,
        "zero_gas_on_failure": False,
        "trust_score": 95,
        "latency_ms": 42,
        "features": ["FCFS定序器", "无公共Mempool", "原生防夹", "毫秒级确认"],
        "setup_guide": "Arbitrum 官方定序器采用先进先出 (FCFS) 撮合，天然不存在以太坊主网级别的三明治夹子。",
        "network_config": {
            "chainId": "0xa4b1",
            "chainName": "Arbitrum One (Direct)",
            "rpcUrls": ["https://arb1.arbitrum.io/rpc"],
            "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
            "blockExplorerUrls": ["https://arbiscan.io"],
        },
    },
    {
        "id": "base_private",
        "name": "Base (Flashblocks Low-Latency)",
        "chain_id": 8453,
        "chain_name": "Base",
        "rpc_url": "https://mainnet.base.org",
        "fast_rpc_url": "https://mainnet.base.org",
        "website": "https://base.org",
        "anti_sandwich": True,
        "anti_frontrunning": True,
        "mev_refund": False,
        "mev_refund_pct": 0,
        "zero_gas_on_failure": False,
        "trust_score": 95,
        "latency_ms": 38,
        "features": ["Coinbase背书", "200ms闪电出块", "定序器直接确认"],
        "setup_guide": "Base 官方直接提交节点，无公开内存池暴露风险，适宜各类批量任务高频交互。",
        "network_config": {
            "chainId": "0x2105",
            "chainName": "Base (Official)",
            "rpcUrls": ["https://mainnet.base.org"],
            "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
            "blockExplorerUrls": ["https://basescan.org"],
        },
    },
]


# 预索引哈希字典，提供 O(1) 毫秒级私有 RPC 节点信息检索
_MEV_NODE_MAP: dict[str, dict[str, Any]] = {n["id"]: n for n in PRESET_MEV_RPC_NODES}


def _live_queries_enabled(allow_live: bool | None) -> bool:
    if allow_live is not None:
        return allow_live
    return settings.app_env.lower() not in {"test", "testing"}


def _validate_custom_rpc_url(raw_url: str) -> str:
    """校验用户提交的自定义 RPC URL（强制 https:// 且拒绝回环/内网/云元数据地址）。"""
    candidate = raw_url.strip()
    if not candidate:
        raise BlockedTargetError("<empty custom_url>")
    try:
        parsed = httpx.URL(candidate)
    except Exception as exc:
        raise BlockedTargetError(f"invalid_url:{candidate[:80]}") from exc

    if parsed.scheme.lower() != "https":
        raise BlockedTargetError("non_https_scheme")

    host = (parsed.host or "").strip("[]").lower()
    if not host or host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise BlockedTargetError(host or "<empty host>")

    try:
        literal = ipaddress.ip_address(host.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None and not _is_safe_public_ip(literal):
        raise BlockedTargetError(host)

    return str(parsed)


def list_mev_rpc_nodes(chain_id: int | None = None) -> list[dict[str, Any]]:
    """获取所有受支持的防 MEV 私有 RPC 节点信息."""
    if chain_id is not None:
        return [n for n in PRESET_MEV_RPC_NODES if n["chain_id"] == chain_id]
    return PRESET_MEV_RPC_NODES


def benchmark_rpc_node(node_id: str | None = None, custom_url: str | None = None) -> dict[str, Any]:
    """生成指定或自定义 RPC 节点的静态防护画像与预设估值延迟（离线兜底/基线计算）."""
    preset = _MEV_NODE_MAP.get(node_id) if node_id else None
    selected: dict[str, Any]
    if preset is not None:
        selected = dict(preset)
    else:
        url = custom_url or "https://rpc.mevblocker.io"
        selected = {
            "id": "custom_node",
            "name": "Custom Private RPC",
            "chain_id": 1,
            "chain_name": "EVM Network",
            "rpc_url": url,
            "fast_rpc_url": url,
            "website": "",
            "anti_sandwich": "mev" in url.lower() or "flashbot" in url.lower(),
            "anti_frontrunning": "mev" in url.lower() or "flashbot" in url.lower(),
            "mev_refund": "mevblocker" in url.lower(),
            "mev_refund_pct": 90 if "mevblocker" in url.lower() else 0,
            "zero_gas_on_failure": True,
            "trust_score": 88,
            "latency_ms": 72,
            "features": ["自定义私有节点", "Mempool隐私保护"],
            "setup_guide": "自定义 RPC 节点，请确保服务提供商信誉良好且不记录 IP 地址。",
            "network_config": {
                "chainId": "0x1",
                "chainName": "Custom EVM",
                "rpcUrls": [url],
                "nativeCurrency": {"name": "Ether", "symbol": "ETH", "decimals": 18},
                "blockExplorerUrls": ["https://etherscan.io"],
            },
        }

    simulated_latency = selected.get("latency_ms", 60)

    if selected.get("anti_sandwich") and selected.get("mev_refund"):
        rating = "A+"
        grade_desc = "顶级防护 (防夹 + 90%利润现金回退)"
    elif selected.get("anti_sandwich"):
        rating = "A"
        grade_desc = "强力防护 (完全阻断公开 Mempool 夹子)"
    else:
        rating = "B"
        grade_desc = "基础连通 (需警惕高滑点交易)"

    return {
        "status": "online",
        "node_info": selected,
        "latency_ms": simulated_latency,
        "safety_rating": rating,
        "rating_description": grade_desc,
        "tested_at": int(time.time()),
        "recommended_for": [
            "大额代币兑换 (Uniswap / Curve)",
            "空投代币领取代币秒砸 (Claim & Instant Sell)",
            "高价值 NFT 抢购与铸造",
        ],
    }


async def benchmark_rpc_node_live(
    node_id: str | None = None,
    custom_url: str | None = None,
    *,
    allow_live: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """对目标 RPC 节点发起真实 JSON-RPC (`eth_blockNumber`) 毫秒级往返测速。

    安全保证：
    - 自定义 URL 强制 `https://` 且走 `_PinnedPublicIPBackend` + `_reject_non_public_target`
      双层公网 IP 绑定校验，阻断内网探测与 DNS 重绑定。
    - 离线/测试环境（`APP_ENV in ("test", "testing")` 且未显式指定 `allow_live=True`）或远端超时时，
      返回 `(baseline, False)` 由路由层诚实标注 `simulated`。
    """
    normalized_custom: str | None = None
    if custom_url is not None and custom_url.strip():
        normalized_custom = _validate_custom_rpc_url(custom_url)

    baseline = benchmark_rpc_node(node_id=node_id, custom_url=normalized_custom)
    if not _live_queries_enabled(allow_live):
        return baseline, False

    probe_url = str(baseline["node_info"]["rpc_url"])
    rpc_body = {"jsonrpc": "2.0", "method": "eth_blockNumber", "params": [], "id": 1}

    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=httpx.Timeout(_RPC_PROBE_TIMEOUT_SECONDS),
            headers={"Content-Type": "application/json", "User-Agent": "airdrop-alpha/1.0 rpc-benchmark"},
            trust_env=False,
            transport=_build_pinned_transport(),
            event_hooks={"request": [_reject_non_public_target]},
        ) as client:
            t0 = time.perf_counter()
            resp = await client.post(probe_url, json=rpc_body)
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        if resp.status_code >= 500:
            raise httpx.HTTPStatusError(
                f"RPC upstream returned {resp.status_code}",
                request=resp.request,
                response=resp,
            )

        payload = resp.json()
        if not isinstance(payload, dict) or ("result" not in payload and "error" not in payload):
            raise ValueError("Invalid JSON-RPC response envelope")

        live_node_info = {**baseline["node_info"], "latency_ms": elapsed_ms}
        live_result: dict[str, Any] = {
            **baseline,
            "node_info": live_node_info,
            "latency_ms": elapsed_ms,
            "tested_at": int(time.time()),
        }
        raw_block = payload.get("result")
        if isinstance(raw_block, str) and raw_block.startswith("0x"):
            live_result["latest_block"] = int(raw_block, 16)
        return live_result, True
    except BlockedTargetError:
        raise
    except Exception as exc:
        logger.warning(
            "mev_rpc.benchmark_live_failed",
            node_id=node_id or "custom_node",
            error_type=type(exc).__name__,
            error=redact(str(exc))[:200],
        )
        return baseline, False
