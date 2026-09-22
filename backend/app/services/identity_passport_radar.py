"""Web3 Identity & Proof of Humanity Radar (链上人机身份凭证聚合与 Gitcoin Passport 戳记提升服务).

聚合 Gitcoin Passport、Linea POH、EAS (Ethereum Attestation Service)、ENS、Lens、Guild Pin 等凭证维度，
计算钱包综合人机置信度得分（判定是否通过 20+ 分防女巫安全线），
按获取成本从低到高（0成本 / <$1 / <$5）推荐最优盖戳路径 (Stamping Guide)。
"""

from __future__ import annotations

import time
from typing import Any
import structlog

logger = structlog.get_logger(__name__)

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


def evaluate_wallet_identity(wallet_address: str) -> dict[str, Any]:
    """根据钱包地址模拟评估链上人机身份得分与凭证状态."""
    clean_addr = wallet_address.strip().lower()
    
    # 模拟真实多维度激活情况 (基于地址哈希伪随机，保证同一地址结果幂等稳定)
    hash_val = sum(ord(c) for c in clean_addr)
    
    active_stamps: list[dict[str, Any]] = []
    missing_stamps: list[dict[str, Any]] = []
    
    total_score = 0.0
    for idx, stamp in enumerate(PASSPORT_STAMPS_CATALOG):
        # 模拟部分戳记已激活
        is_active = ((hash_val + idx * 7) % 3) != 0
        if is_active:
            active_stamps.append(stamp)
            total_score += stamp["weight"]
        else:
            missing_stamps.append(stamp)

    rounded_score = round(total_score, 2)
    is_human_verified = rounded_score >= 20.0
    
    if rounded_score >= 28.0:
        tier = "ELITE_HUMAN"
        tier_desc = "顶级真人猎人 (防女巫免疫，享最高空投乘数)"
    elif rounded_score >= 20.0:
        tier = "CERTIFIED_HUMAN"
        tier_desc = "合格真人 (满足主流项目快照防女巫基准线 20 分)"
    elif rounded_score >= 12.0:
        tier = "MARGINAL_RISK"
        tier_desc = "临界风险 (距离 20 分仅缺 2-3 个戳记，极易被严格筛查误杀)"
    else:
        tier = "HIGH_SYBIL_SUSPECT"
        tier_desc = "高危女巫嫌疑 (缺少核心社交与链上凭证，亟需补齐)"

    return {
        "wallet_address": wallet_address,
        "passport_score": rounded_score,
        "human_threshold": 20.0,
        "is_human_verified": is_human_verified,
        "tier": tier,
        "tier_description": tier_desc,
        "active_stamps_count": len(active_stamps),
        "missing_stamps_count": len(missing_stamps),
        "active_stamps": active_stamps,
        "missing_stamps": missing_stamps,
        "recommended_next_stamps": sorted(
            missing_stamps,
            key=lambda x: (x["cost_usd"], -x["weight"])
        )[:4],
    }


def get_stamping_guide() -> list[dict[str, Any]]:
    """获取所有受支持的戳记目录，并按性价比（分值/成本）排序."""
    # 计算 ROI 指标: 分值 / (成本 + 0.1 防止除以0)
    sorted_catalog = sorted(
        PASSPORT_STAMPS_CATALOG,
        key=lambda s: (s["weight"] / (s["cost_usd"] + 0.2)),
        reverse=True,
    )
    return sorted_catalog
