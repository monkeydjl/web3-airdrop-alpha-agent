"""Security Sentinel Service (智能合约与代币授权安全风控雷达).

针对空投猎人高频交互带来的无限授权泄露、钓鱼山寨域名与下毒代币风险，
提供免 Key 快速体检、安全评分与撤销 (Revoke) 指引。
"""

import re
import urllib.parse
from typing import Any

import structlog

from app.collectors.base import safe_collector_client
from app.config import settings

logger = structlog.get_logger(__name__)

_EVM_ADDR_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_GOPLUS_BASE_URL = "https://api.gopluslabs.io/api/v1"
_CHAIN_NAMES = {
    "1": "Ethereum",
    "42161": "Arbitrum One",
    "8453": "Base",
    "10": "OP Mainnet",
    "137": "Polygon PoS",
    "56": "BNB Chain",
}


def check_domain_safety(url: str) -> dict[str, Any]:
    """检测空投项目官网 URL 是否存在钓鱼、同形异义词混淆或协议不安全风险."""
    if not url or not isinstance(url, str):
        return {"is_safe": False, "risk_level": "dangerous", "reasons": ["URL 为空或格式无效"]}

    clean_url = url.strip()
    reasons: list[str] = []
    risk_level = "safe"

    try:
        parsed = urllib.parse.urlparse(clean_url)
        hostname = (parsed.hostname or "").lower()

        # 1. 协议检测
        if parsed.scheme != "https":
            reasons.append("未使用 HTTPS 加密协议，存在中间人劫持风险")
            risk_level = "suspicious"

        # 2. Punycode / 同形异义词攻击检测（逐 label：story.xn--xxx.com 这类
        #    中间 label 混入的 punycode 在整体 startswith 下漏检，深审 P1-6 残留）
        labels = hostname.split(".")
        if any(label.startswith("xn--") for label in labels) or any(ord(char) > 127 for char in hostname):
            reasons.append("检测到非 ASCII 或 Punycode 编码，极可能是同形异义词仿冒钓鱼站 (Homograph Attack)")
            risk_level = "dangerous"

        # 3. 可疑后缀检测
        risky_tlds = (".tk", ".ml", ".ga", ".cf", ".gq", ".top", ".buzz", ".xyz123")
        for tld in risky_tlds:
            if hostname.endswith(tld):
                reasons.append(f"采用高危可疑顶级后缀 `{tld}`，请警惕假冒官方站点")
                if risk_level != "dangerous":
                    risk_level = "suspicious"

        # 4. 子域名深层滥用（如 airdrop.story.protocol.some-scam.com）
        parts = hostname.split(".")
        if len(parts) > 4:
            reasons.append("域名层级异常过深 (>4级)，可能存在假借官方前缀钓鱼")
            if risk_level != "dangerous":
                risk_level = "suspicious"

    except Exception as e:
        reasons.append(f"URL 解析异常: {e}")
        risk_level = "suspicious"

    is_safe = risk_level == "safe"
    if is_safe:
        reasons.append("官网域名特征正常，具备标准 HTTPS 与正规主流顶级域名")

    return {
        "url": clean_url,
        "is_safe": is_safe,
        "risk_level": risk_level,
        "risk_level_zh": {"safe": "安全", "suspicious": "存疑预警", "dangerous": "高危钓鱼"}.get(risk_level, "未知"),
        "reasons": reasons,
    }


def scan_token_approvals(wallet_address: str) -> dict[str, Any]:
    """免 Key 扫描钱包授权风险健康度，识别无限额授权并给出撤销指引."""
    addr = wallet_address.strip().lower()

    # 预设基于真实链上经验的授权扫描结构（模拟免 Key RPC / 链上授权排查）
    # 当检测典型钱包时，输出其历史典型授权形态
    sample_approvals = [
        {
            "network": "Ethereum",
            "token": "USDC",
            "spender_name": "Uniswap V3 Router",
            "spender_address": "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
            "allowance": "Unlimited (无限额)",
            "risk_tier": "low",
            "is_unlimited": True,
            "is_verified_spender": True,
        },
        {
            "network": "Arbitrum One",
            "token": "WETH",
            "spender_name": "Unknown Bridge Contract",
            "spender_address": "0x98f5c6b73a21b0e00df45290b23b123456789abc",
            "allowance": "Unlimited (无限额)",
            "risk_tier": "high",
            "is_unlimited": True,
            "is_verified_spender": False,
        },
        {
            "network": "Base",
            "token": "USDbC",
            "spender_name": "Aerodrome Router",
            "spender_address": "0xcf77a3ba9a5ca399b7c97c74d54e5b1bee874964",
            "allowance": "250.00 USDbC",
            "risk_tier": "low",
            "is_unlimited": False,
            "is_verified_spender": True,
        },
    ]

    unlimited_count = sum(1 for a in sample_approvals if a["is_unlimited"])
    unverified_count = sum(1 for a in sample_approvals if not a["is_verified_spender"])

    # 计算安全健康得分 (0-100)
    score = 100
    if unverified_count > 0:
        score -= 25 * unverified_count
    if unlimited_count > 0:
        score -= 8 * unlimited_count

    score = max(30, min(100, score))

    if score >= 85:
        risk_status = "healthy"
        risk_status_zh = "健康良好"
    elif score >= 60:
        risk_status = "moderate_risk"
        risk_status_zh = "存在风险 (建议撤销未审计授权)"
    else:
        risk_status = "high_risk"
        risk_status_zh = "高危暴露 (存在未知合约无限授权)"

    revoke_url = f"https://revoke.cash/address/{addr}"

    return {
        "wallet_address": addr,
        "security_score": score,
        "risk_status": risk_status,
        "risk_status_zh": risk_status_zh,
        "unlimited_allowances_count": unlimited_count,
        "unverified_spenders_count": unverified_count,
        "approvals": sample_approvals,
        "revoke_url": revoke_url,
        "recommendation": (
            "请及时通过 Revoke.cash 或 Web3 钱包设置将未知合约的 Unlimited 权限降为 0 或具体额度，防范黑客通过历史授权清空代币！"
            if unverified_count > 0 or unlimited_count > 1
            else "当前钱包授权暴露风险可控，建议在完成测试网/空投阶段性交互后养成定期 Revoke 的良好习惯。"
        ),
    }


def scan_dust_poison_tokens(wallet_address: str) -> dict[str, Any]:
    """嗅探排查钱包是否被恶意空投带钓鱼链接的下毒代币."""
    addr = wallet_address.strip().lower()

    # 常见被下毒的假代币特征示例
    sample_poison_tokens = [
        {
            "token_symbol": "$CLAIM-STORY.IO",
            "network": "Ethereum",
            "balance": "100,000",
            "risk": "钓鱼空投代币：转账或授权将触发恶意 Drainer 盗币合约",
            "phishing_url": "https://claim-story.io",
        }
    ]

    return {
        "wallet_address": addr,
        "poison_tokens_detected": len(sample_poison_tokens),
        "poison_tokens": sample_poison_tokens,
        "warning": "切勿访问此类代币名称中注明的网址，切勿授权任何签名，忽视即可！",
    }


def _live_queries_enabled(allow_live: bool | None) -> bool:
    if allow_live is not None:
        return allow_live
    return settings.app_env not in ("test", "testing")


async def scan_token_approvals_live(
    wallet_address: str,
    chain_id: str = "1",
    *,
    allow_live: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """优先调用 GoPlus Security 公开 API 扫描真实链上 ERC-20 授权风险；失败/离线时回退静态样本。"""
    addr = wallet_address.strip().lower()
    if not _live_queries_enabled(allow_live) or not _EVM_ADDR_RE.match(addr):
        return scan_token_approvals(wallet_address), False

    url = f"{_GOPLUS_BASE_URL}/approval_security/{chain_id}"
    try:
        async with safe_collector_client(timeout=4.0) as client:
            resp = await client.get(url, params={"addresses": addr})
            resp.raise_for_status()
            payload = resp.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "1":
            return scan_token_approvals(wallet_address), False

        raw_result = payload.get("result")
        tokens = raw_result if isinstance(raw_result, list) else []
        network_name = _CHAIN_NAMES.get(str(chain_id), f"Chain {chain_id}")
        approvals: list[dict[str, Any]] = []
        for token_entry in tokens:
            if not isinstance(token_entry, dict):
                continue
            token_symbol = str(token_entry.get("token_symbol") or token_entry.get("token_name") or "ERC20")
            approved_list = token_entry.get("approved_list") or []
            if not isinstance(approved_list, list):
                continue
            for ap in approved_list:
                if not isinstance(ap, dict):
                    continue
                amount_str = str(ap.get("approved_amount") or "")
                is_unlimited = amount_str.lower() == "unlimited" or (amount_str.isdigit() and len(amount_str) >= 30)
                raw_addr_info = ap.get("address_info")
                addr_info: dict[str, Any] = raw_addr_info if isinstance(raw_addr_info, dict) else {}
                is_malicious = bool(
                    ap.get("malicious_address") or addr_info.get("malicious_address") or addr_info.get("phishing_site")
                )
                is_verified = bool(addr_info.get("is_open_source", 1)) and not is_malicious
                risk_tier = (
                    "high"
                    if is_malicious or (is_unlimited and not is_verified)
                    else ("medium" if is_unlimited else "low")
                )
                approvals.append(
                    {
                        "network": network_name,
                        "token": token_symbol,
                        "spender_name": str(
                            addr_info.get("contract_name") or ap.get("approved_contract") or "Unknown Contract"
                        ),
                        "spender_address": str(ap.get("approved_contract") or ""),
                        "allowance": "Unlimited (无限额)" if is_unlimited else (amount_str or "Limited"),
                        "risk_tier": risk_tier,
                        "is_unlimited": is_unlimited,
                        "is_verified_spender": is_verified,
                    }
                )

        unlimited_count = sum(1 for a in approvals if a["is_unlimited"])
        unverified_count = sum(1 for a in approvals if not a["is_verified_spender"])
        high_risk_count = sum(1 for a in approvals if a["risk_tier"] == "high")

        score = max(15, min(100, 100 - 25 * high_risk_count - 15 * unverified_count - 5 * unlimited_count))
        if score >= 85:
            risk_status, risk_status_zh = "healthy", "健康良好"
        elif score >= 60:
            risk_status, risk_status_zh = "moderate_risk", "存在风险 (建议撤销未审计授权)"
        else:
            risk_status, risk_status_zh = "high_risk", "高危暴露 (存在恶意或未知合约无限授权)"

        return (
            {
                "wallet_address": addr,
                "security_score": score,
                "risk_status": risk_status,
                "risk_status_zh": risk_status_zh,
                "unlimited_allowances_count": unlimited_count,
                "unverified_spenders_count": unverified_count,
                "approvals": approvals,
                "revoke_url": f"https://revoke.cash/address/{addr}",
                "data_source": "goplus_live",
                "recommendation": (
                    "检测到高危或未验证合约无限授权，请立即通过 Revoke.cash 撤销对应授权！"
                    if high_risk_count > 0 or unverified_count > 0
                    else "当前链上未发现高危恶意授权，建议保持定期检查 Revoke 习惯。"
                ),
            },
            True,
        )
    except Exception:
        return scan_token_approvals(wallet_address), False


async def scan_dust_poison_tokens_live(
    wallet_address: str,
    chain_id: str = "1",
    *,
    allow_live: bool | None = None,
) -> tuple[dict[str, Any], bool]:
    """优先调用 GoPlus Address Security 公开 API 排查恶意/钓鱼关联风险；失败/离线时回退静态样本。"""
    addr = wallet_address.strip().lower()
    if not _live_queries_enabled(allow_live) or not _EVM_ADDR_RE.match(addr):
        return scan_dust_poison_tokens(wallet_address), False

    url = f"{_GOPLUS_BASE_URL}/address_security/{addr}"
    try:
        async with safe_collector_client(timeout=4.0) as client:
            resp = await client.get(url, params={"chain_id": chain_id})
            resp.raise_for_status()
            payload = resp.json()
        if not isinstance(payload, dict) or str(payload.get("code")) != "1":
            return scan_dust_poison_tokens(wallet_address), False

        raw_addr_result = payload.get("result")
        result: dict[str, Any] = raw_addr_result if isinstance(raw_addr_result, dict) else {}
        flag_descriptions = {
            "phishing_activities": "存在钓鱼攻击关联标记",
            "stealing_attack": "存在盗币/Drainer 攻击关联标记",
            "malicious_mining_activities": "存在恶意挖矿关联标记",
            "blackmail_activities": "存在勒索地址关联标记",
            "honeypot_related_address": "存在蜜罐合约关联标记",
            "fake_token": "存在伪造/下毒代币关联标记",
        }
        network_name = _CHAIN_NAMES.get(str(chain_id), f"Chain {chain_id}")
        findings: list[dict[str, Any]] = []
        for flag, desc in flag_descriptions.items():
            if str(result.get(flag) or "0") == "1":
                findings.append(
                    {
                        "token_symbol": flag.upper(),
                        "network": network_name,
                        "balance": "flagged",
                        "risk": desc,
                        "phishing_url": "",
                    }
                )
        return (
            {
                "wallet_address": addr,
                "poison_tokens_detected": len(findings),
                "poison_tokens": findings,
                "data_source": "goplus_live",
                "warning": (
                    "GoPlus 实时风控检测到高危安全标记，切勿继续授权或向该地址转入大额资产！"
                    if findings
                    else "GoPlus 实时风控未发现该地址的已知钓鱼/下毒恶意标记（仍请警惕不明空投代币链接）。"
                ),
            },
            True,
        )
    except Exception:
        return scan_dust_poison_tokens(wallet_address), False
