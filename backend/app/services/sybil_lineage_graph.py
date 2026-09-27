"""Multi-Wallet Sybil Lineage Education Graph (多钱包隔离自查与教学图谱).

诚实口径（2026-09-23 审计，docs/EXPANSION_AUDIT_REPORT.md）：

此服务历史上用 ``md5(addr1_addr2) % 7 == 0`` 这类哈希取模「检测」资金关联，
并生成 ``0xfa1100...funder`` 等**不存在的假地址**冒充链上发现——用户会基于
虚构的「女巫红线」改变真实资金操作，危害最大。

真实的资金血缘检测必须查询链上转账记录（Etherscan/Alchemy 等），没有数据源
就无法检测。因此本服务现在只做两类**诚实的**输出：

1. ``lineage_status``：输入地址间的**结构性自查**——完全基于地址字面量
   （互转检测只在用户自己声明时才成立，见 ``declared_links`` 参数），
   不假装知道链上发生了什么。
2. ``education``：防关联隔离的教学拓扑与通用红线清单（与 onchain_sybil
   的拓扑生成器同源的确定性知识），不针对具体地址捏造发现。

任何「检测到 XX 关联」的输出在接入真实链上数据前一律不存在。
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 教学内容：与 app/services/onchain_sybil.py 保持同一套确定性知识
_EDUCATION_CRITICAL_RULES = [
    "绝对零互转：参与同一项目的任意两个钱包之间不能产生任何转账或授权交互。",
    "出金与入金隔离：从交易所提现时使用不同子账户；空投发币后充值到各子账户的独立充值地址，严禁链上归集。",
    "时间随机离散化：避免同一时间段批量按相同顺序做相同交互，间隔分散数小时至数天。",
    "金额随机小数化：避免完全相同的整齐金额，每次加入随机微量浮动。",
    "环境与指纹隔离：指纹浏览器配合不同静态住宅代理 IP，避免 Web 指纹同源。",
]


def analyze_wallet_lineage(
    wallet_addresses: list[str],
    declared_links: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """多钱包隔离自查 + 教学图谱.

    Args:
        wallet_addresses: 待自查的地址列表（2~50 个）。
        declared_links: 用户**自行声明**的钱包间关联（如确知自己误转过），
            形如 ``{"source": "0x..", "target": "0x..", "label": "误转"}``。
            服务端不猜测链上事实，只处理用户显式提供的关联。

    Returns:
        含 ``lineage_status``（结构性自查）、``education``（教学红线）、
        ``nodes``/``links``（仅用户声明的关系 + 目标钱包节点）的 dict。
    """
    cleaned_addrs = [a.lower().strip() for a in wallet_addresses if a and a.strip().startswith("0x")]
    unique_addrs = list(dict.fromkeys(cleaned_addrs))

    if len(unique_addrs) < 2:
        return {
            "ok": True,
            "wallets_analyzed": len(unique_addrs),
            "lineage_status": "insufficient_input",
            "isolation_score": None,
            "risk_level": None,
            "sybil_cluster_detected": False,
            "nodes": [
                {"id": a, "label": f"{a[:6]}...{a[-4:]}", "role": "target_wallet", "risk": "unknown"}
                for a in unique_addrs
            ],
            "links": [],
            "fatal_red_flags": [],
            "recommendations": [
                "至少输入 2 个钱包才能做结构性自查。",
                "提示：真正的资金血缘检测需要查询链上转账记录；本工具只能做结构性自查与隔离教学。",
            ],
            "education": {"critical_rules": _EDUCATION_CRITICAL_RULES},
        }

    nodes: list[dict[str, Any]] = [
        {"id": a, "label": f"Wallet #{i + 1} ({a[:6]}...{a[-4:]})", "role": "target_wallet", "risk": "unknown"}
        for i, a in enumerate(unique_addrs)
    ]

    # 只处理用户显式声明的关联——服务端不编造链上事实
    declared = []
    fatal_red_flags: list[str] = []
    if declared_links:
        addr_set = set(unique_addrs)
        for link in declared_links:
            src = str(link.get("source", "")).lower().strip()
            dst = str(link.get("target", "")).lower().strip()
            if src in addr_set and dst in addr_set and src != dst:
                declared.append(
                    {
                        "source": src,
                        "target": dst,
                        "type": "declared",
                        "label": str(link.get("label") or "用户声明关联"),
                        "severity": "fatal",
                    }
                )
                fatal_red_flags.append(
                    f"用户声明关联: {src[:6]}...{src[-4:]} 与 {dst[:6]}...{dst[-4:]} 存在直接关联（{link.get('label') or '声明'}）"
                )

    links: list[dict[str, Any]] = list(declared)

    has_declared_fatal = bool(declared)
    isolation_score = 55 if has_declared_fatal else None
    risk_level = "user_declared_risk" if has_declared_fatal else None

    recommendations = [
        "真正的资金血缘检测需要链上转账数据源（Etherscan/Alchemy 等）；接入前本工具不假装能检测。",
        "可对照下方教学红线自行核对你的出入金路径是否合规。",
    ]
    if has_declared_fatal:
        recommendations.insert(
            0, "存在你自行声明的钱包间直接关联——这属于反女巫系统的致命红线，建议立即停止相关钱包的后续交互。"
        )

    return {
        "ok": True,
        "wallets_analyzed": len(unique_addrs),
        "lineage_status": "user_declared_links_found" if has_declared_fatal else "no_declared_links",
        "isolation_score": isolation_score,
        "risk_level": risk_level,
        "sybil_cluster_detected": has_declared_fatal,
        "nodes": nodes,
        "links": links,
        "fatal_red_flags": fatal_red_flags,
        "recommendations": recommendations,
        "education": {"critical_rules": _EDUCATION_CRITICAL_RULES},
    }
