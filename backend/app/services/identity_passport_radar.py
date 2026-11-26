"""Web3 Identity & Proof of Humanity Radar (链上人机身份凭证聚合与 Gitcoin Passport 戳记提升服务).

聚合 Gitcoin Passport、Linea POH、ENS、Snapshot DAO、Gnosis Safe 等凭证维度，
优先通过免 Key 公共链上 RPC 与开放 API 实测可验证凭证，并结合用户显式声明的链下社交戳记，
计算钱包综合人机置信度得分（判定是否通过 20+ 分防女巫安全线）与最优盖戳路径 (Stamping Guide)。
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import httpx
import structlog

from app.config import settings
from app.utils.redact import redact

logger = structlog.get_logger(__name__)

_EVM_ADDRESS_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")
_PROBE_TIMEOUT_SECONDS = 3.5

# Ethereum Mainnet ENS ReverseRecords 合约：getNames(address[]) selector = 0x55ea6c47
_ENS_REVERSE_RECORDS_CONTRACT = "0x3671aE578E63FdF66ad4F3E12CC0c0d71Ac7510C"
_MAINNET_RPC_URL = "https://ethereum-rpc.publicnode.com"
_SAFE_CHECK_RPCS: tuple[tuple[str, str], ...] = (
    ("ethereum", _MAINNET_RPC_URL),
    ("arbitrum", "https://arb1.arbitrum.io/rpc"),
    ("base", "https://mainnet.base.org"),
)
_LINEA_POH_API_TEMPLATE = "https://poh-api.linea.build/poh/v2/{address}"
_SNAPSHOT_GRAPHQL_URL = "https://hub.snapshot.org/graphql"

# Gitcoin Passport 及主流人机戳记知识库与加权规则
PASSPORT_STAMPS_CATALOG: list[dict[str, Any]] = [
    {
        "id": "stamp_github",
        "name": "GitHub 开发者认证",
        "provider": "Gitcoin Passport",
        "category": "social",
        "weight": 3.65,
        "cost_usd": 0.0,
        "difficulty": "Easy",
        "guide": "绑定活跃 GitHub 账号，拥有 90 天以上历史或开源贡献即可免费解锁。",
    },
    {
        "id": "stamp_twitter",
        "name": "Twitter / X 社交认证",
        "provider": "Gitcoin Passport",
        "category": "social",
        "weight": 2.45,
        "cost_usd": 0.0,
        "difficulty": "Easy",
        "guide": "连接推特账号，拥有 10+ 关注者与历史发推即可获得。",
    },
    {
        "id": "stamp_discord",
        "name": "Discord 社区成员",
        "provider": "Gitcoin Passport",
        "category": "social",
        "weight": 1.85,
        "cost_usd": 0.0,
        "difficulty": "Easy",
        "guide": "连接 Discord 授权验证，零成本。",
    },
    {
        "id": "stamp_google",
        "name": "Google 真实账户认证",
        "provider": "Gitcoin Passport",
        "category": "social",
        "weight": 2.25,
        "cost_usd": 0.0,
        "difficulty": "Easy",
        "guide": "Google 账号 OAuth 单点认证，零成本。",
    },
    {
        "id": "stamp_ens",
        "name": "ENS 域名所有者",
        "provider": "Ethereum Mainnet",
        "category": "onchain",
        "weight": 3.80,
        "cost_usd": 5.0,
        "difficulty": "Medium",
        "guide": "持有主网 .eth 域名并设置主解析反向记录。",
    },
    {
        "id": "stamp_snapshot",
        "name": "Snapshot DAO 治理投票人",
        "provider": "Snapshot",
        "category": "governance",
        "weight": 2.90,
        "cost_usd": 0.0,
        "difficulty": "Easy",
        "guide": "参与至少 2 次链下 DAO 免费离线签名提案投票（如 Arbitrum / Aave / Uniswap）。",
    },
    {
        "id": "stamp_safe",
        "name": "Gnosis Safe 多签钱包所有者",
        "provider": "Safe Global",
        "category": "security",
        "weight": 4.10,
        "cost_usd": 1.5,
        "difficulty": "Medium",
        "guide": "在 L2 (Arbitrum/Base) 免费或极低 Gas 部署一个 Safe 多签合约并设为签名人。",
    },
    {
        "id": "stamp_holonym",
        "name": "Holonym 零知识真人认证 (ZK-ID)",
        "provider": "Holonym / Silk",
        "category": "zk_id",
        "weight": 6.50,
        "cost_usd": 0.0,
        "difficulty": "Medium",
        "guide": "采用零知识电话或护照匿名校验，一次性增加 6.5 分高权重，绝不泄露隐私。",
    },
    {
        "id": "stamp_linea_poh",
        "name": "Linea Proof of Humanity (POH)",
        "provider": "Linea / Verax",
        "category": "poh",
        "weight": 5.00,
        "cost_usd": 1.0,
        "difficulty": "Medium",
        "guide": "通过 Group A (Trusta/Nomis) 与 Group B 认证，直接获得 Linea 专属空投加成。",
    },
    {
        "id": "stamp_guild_pin",
        "name": "Guild.xyz 会员徽章",
        "provider": "Guild.xyz",
        "category": "community",
        "weight": 2.10,
        "cost_usd": 1.0,
        "difficulty": "Easy",
        "guide": "在任意主流协议 Guild 达成角色并铸造 Guild Pin NFT。",
    },
]

_VALID_STAMP_IDS: frozenset[str] = frozenset(s["id"] for s in PASSPORT_STAMPS_CATALOG)


def _live_queries_enabled(allow_live: bool | None) -> bool:
    if allow_live is not None:
        return allow_live
    return settings.app_env.lower() not in {"test", "testing"}


def _classify_identity_tier(rounded_score: float) -> tuple[str, str]:
    if rounded_score >= 28.0:
        return "ELITE_HUMAN", "顶级真人猎人 (防女巫免疫，享最高空投乘数)"
    if rounded_score >= 20.0:
        return "CERTIFIED_HUMAN", "合格真人 (满足主流项目快照防女巫基准线 20 分)"
    if rounded_score >= 12.0:
        return "MARGINAL_RISK", "临界风险 (距离 20 分仅缺 2-3 个戳记，极易被严格筛查误杀)"
    return "HIGH_SYBIL_SUSPECT", "高危女巫嫌疑 (缺少核心社交与链上凭证，亟需补齐)"


def _build_identity_payload(
    wallet_address: str,
    active_ids: set[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    active_stamps: list[dict[str, Any]] = []
    missing_stamps: list[dict[str, Any]] = []
    total_score = 0.0

    for stamp in PASSPORT_STAMPS_CATALOG:
        if stamp["id"] in active_ids:
            active_stamps.append(dict(stamp))
            total_score += float(stamp["weight"])
        else:
            missing_stamps.append(dict(stamp))

    rounded_score = round(total_score, 2)
    tier, tier_desc = _classify_identity_tier(rounded_score)
    out: dict[str, Any] = {
        "wallet_address": wallet_address,
        "passport_score": rounded_score,
        "human_threshold": 20.0,
        "is_human_verified": rounded_score >= 20.0,
        "tier": tier,
        "tier_description": tier_desc,
        "active_stamps_count": len(active_stamps),
        "missing_stamps_count": len(missing_stamps),
        "active_stamps": active_stamps,
        "missing_stamps": missing_stamps,
        "recommended_next_stamps": sorted(missing_stamps, key=lambda x: (x["cost_usd"], -x["weight"]))[:4],
    }
    if extra:
        out.update(extra)
    return out


def evaluate_wallet_identity(wallet_address: str) -> dict[str, Any]:
    """离线兜底：根据钱包地址确定性生成演示身份评估结构（仅离线/测试回退使用）."""
    clean_addr = wallet_address.strip().lower()
    hash_val = sum(ord(c) for c in clean_addr)
    active_ids = {stamp["id"] for idx, stamp in enumerate(PASSPORT_STAMPS_CATALOG) if ((hash_val + idx * 7) % 3) != 0}
    return _build_identity_payload(wallet_address, active_ids)


def _encode_ens_get_names_calldata(addr_hex_no_prefix: str) -> str:
    """编码 ReverseRecords.getNames([addr]) ABI calldata."""
    padded_addr = addr_hex_no_prefix.lower().rjust(64, "0")
    offset = (32).to_bytes(32, "big").hex()
    length = (1).to_bytes(32, "big").hex()
    return f"0x55ea6c47{offset}{length}{padded_addr}"


def _decode_first_abi_string_array(hex_result: str) -> str | None:
    """从 ABI `string[]` 返回值中解码第 0 个字符串；为空或格式不符返回 None."""
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64 * 4:
        return None
    try:
        data = bytes.fromhex(raw)
        arr_offset = int.from_bytes(data[0:32], "big")
        if arr_offset + 64 > len(data):
            return None
        arr_len = int.from_bytes(data[arr_offset : arr_offset + 32], "big")
        if arr_len < 1:
            return None
        elem0_rel_offset = int.from_bytes(data[arr_offset + 32 : arr_offset + 64], "big")
        str_pos = arr_offset + 32 + elem0_rel_offset
        if str_pos + 32 > len(data):
            return None
        str_len = int.from_bytes(data[str_pos : str_pos + 32], "big")
        if str_len == 0 or str_pos + 32 + str_len > len(data):
            return None
        decoded = data[str_pos + 32 : str_pos + 32 + str_len].decode("utf-8", errors="strict").strip()
        return decoded or None
    except Exception:
        return None


async def _probe_ens_reverse(client: httpx.AsyncClient, addr: str) -> tuple[bool, str | None]:
    calldata = _encode_ens_get_names_calldata(addr[2:])
    resp = await client.post(
        _MAINNET_RPC_URL,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_call",
            "params": [{"to": _ENS_REVERSE_RECORDS_CONTRACT, "data": calldata}, "latest"],
        },
    )
    resp.raise_for_status()
    payload = resp.json()
    if not isinstance(payload, dict) or "result" not in payload:
        raise ValueError("invalid ens eth_call response")
    name = _decode_first_abi_string_array(str(payload.get("result") or ""))
    return True, name


async def _probe_linea_poh(client: httpx.AsyncClient, addr: str) -> tuple[bool, bool]:
    resp = await client.get(_LINEA_POH_API_TEMPLATE.format(address=addr))
    resp.raise_for_status()
    text = resp.text.strip().lower()
    if text in ("true", "false"):
        return True, text == "true"
    data = resp.json()
    if isinstance(data, bool):
        return True, data
    if isinstance(data, dict):
        return True, bool(data.get("poh") or data.get("verified") or data.get("isHuman"))
    raise ValueError("unexpected linea poh response")


async def _probe_snapshot_votes(client: httpx.AsyncClient, addr: str) -> tuple[bool, int]:
    query = "query($voter: String!) { votes(first: 2, where: { voter: $voter }) { id } }"
    resp = await client.post(
        _SNAPSHOT_GRAPHQL_URL,
        json={"query": query, "variables": {"voter": addr.lower()}},
    )
    resp.raise_for_status()
    payload = resp.json()
    votes = ((payload.get("data") or {}).get("votes")) if isinstance(payload, dict) else None
    if not isinstance(votes, list):
        raise ValueError("invalid snapshot graphql response")
    return True, len(votes)


async def _probe_safe_bytecode(client: httpx.AsyncClient, addr: str) -> tuple[bool, list[str]]:
    async def _one_chain(chain_name: str, rpc_url: str) -> tuple[bool, str | None]:
        resp = await client.post(
            rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": "eth_getCode", "params": [addr, "latest"]},
        )
        resp.raise_for_status()
        body = resp.json()
        code = str(body.get("result") or "0x") if isinstance(body, dict) else "0x"
        # EIP-7702 委托前缀为 0xef0100（23B），常规多签/合约账户字节码 > 2 chars ("0x")
        is_contract = code.startswith("0x") and len(code) > 2 and not code.lower().startswith("0xef0100")
        return True, (chain_name if is_contract else None)

    results = await asyncio.gather(*(_one_chain(c, u) for c, u in _SAFE_CHECK_RPCS), return_exceptions=True)
    any_ok = False
    contract_chains: list[str] = []
    for item in results:
        if isinstance(item, tuple):
            any_ok = True
            if item[1]:
                contract_chains.append(item[1])
    if not any_ok:
        raise RuntimeError("all safe bytecode rpc probes failed")
    return True, contract_chains


async def evaluate_wallet_identity_live(
    wallet_address: str,
    declared_stamps: list[str] | None = None,
    *,
    allow_live: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """实时查询 ENS 反向记录、Linea POH、Snapshot 治理投票与多链合约账户，结合用户声明评估身份分。"""
    clean_addr = wallet_address.strip()
    declared_valid = {
        s.strip() for s in (declared_stamps or []) if isinstance(s, str) and s.strip() in _VALID_STAMP_IDS
    }

    if not _EVM_ADDRESS_RE.match(clean_addr) or not _live_queries_enabled(allow_live):
        if declared_valid:
            return _build_identity_payload(
                clean_addr,
                declared_valid,
                extra={"verification_mode": "declared_only"},
            ), True
        return evaluate_wallet_identity(clean_addr), False

    lower_addr = clean_addr.lower()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(_PROBE_TIMEOUT_SECONDS),
        headers={"User-Agent": "airdrop-alpha/1.0 identity-radar"},
        trust_env=False,
    ) as client:
        ens_res, poh_res, snap_res, safe_res = await asyncio.gather(
            _probe_ens_reverse(client, lower_addr),
            _probe_linea_poh(client, lower_addr),
            _probe_snapshot_votes(client, lower_addr),
            _probe_safe_bytecode(client, lower_addr),
            return_exceptions=True,
        )

    verified_sources_ok = 0
    active_ids: set[str] = set(declared_valid)
    ens_name: str | None = None
    linea_poh_verified: bool | None = None
    snapshot_votes_sampled: int | None = None
    contract_wallet_chains: list[str] = []

    if isinstance(ens_res, tuple):
        verified_sources_ok += 1
        ens_name = ens_res[1]
        if ens_name:
            active_ids.add("stamp_ens")
    if isinstance(poh_res, tuple):
        verified_sources_ok += 1
        linea_poh_verified = poh_res[1]
        if linea_poh_verified:
            active_ids.add("stamp_linea_poh")
    if isinstance(snap_res, tuple):
        verified_sources_ok += 1
        snapshot_votes_sampled = snap_res[1]
        if snapshot_votes_sampled >= 2:
            active_ids.add("stamp_snapshot")
    if isinstance(safe_res, tuple):
        verified_sources_ok += 1
        contract_wallet_chains = safe_res[1]
        if contract_wallet_chains:
            active_ids.add("stamp_safe")

    if verified_sources_ok == 0 and not declared_valid:
        errors = [
            f"{name}:{type(r).__name__}"
            for name, r in (("ens", ens_res), ("linea_poh", poh_res), ("snapshot", snap_res), ("safe", safe_res))
            if isinstance(r, BaseException)
        ]
        logger.warning(
            "identity.live_probe_failed",
            address_prefix=lower_addr[:10],
            errors=redact(",".join(errors))[:200],
        )
        return evaluate_wallet_identity(clean_addr), False

    payload = _build_identity_payload(
        clean_addr,
        active_ids,
        extra={
            "verification_mode": "live_onchain_plus_declared",
            "onchain_verification": {
                "probed_sources": 4,
                "verified_sources_ok": verified_sources_ok,
                "ens_name": ens_name,
                "linea_poh_verified": linea_poh_verified,
                "snapshot_votes_sampled": snapshot_votes_sampled,
                "contract_wallet_chains": contract_wallet_chains,
                "declared_stamps": sorted(declared_valid),
            },
        },
    )
    return payload, True


# 预先在模块加载阶段按性价比（分值/成本）排好序，避免每次 API 调用重复排序
_PRECOMPUTED_STAMPING_GUIDE: list[dict[str, Any]] = sorted(
    PASSPORT_STAMPS_CATALOG,
    key=lambda s: s["weight"] / (s["cost_usd"] + 0.2),
    reverse=True,
)


def get_stamping_guide() -> list[dict[str, Any]]:
    """获取所有受支持的戳记目录，并按性价比（分值/成本）排序 (O(1) 预计算快速返回)."""
    return _PRECOMPUTED_STAMPING_GUIDE
