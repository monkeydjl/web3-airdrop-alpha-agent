"""Hunter Personas & Adaptive Scoring Service (猎人风格偏好切换与自适应动态加权).

支持四种典型猎人画像：
- balanced: 全能平衡模式（系统默认）
- zero_cost: 零成本测试网党（重度强化测试网、水龙头、低资金门槛）
- whale_restaking: 巨鲸质押生息党（大资金安全第一，重度强化 Tier1 机构、大额融资与高 TVL）
- high_beta: 高弹性叙事追逐者（敏锐捕获风口早期 Alpha 与催化剂）
"""

import json
from enum import StrEnum
from typing import Any


class HunterPersonaId(StrEnum):
    BALANCED = "balanced"
    ZERO_COST = "zero_cost"
    WHALE_RESTAKING = "whale_restaking"
    HIGH_BETA = "high_beta"


# 8 维子分键标准列表
SUB_SCORE_KEYS = [
    "airdrop_signal",
    "narrative_timing",
    "team_reputation",
    "risk",
    "tokenomics",
    "competition",
    "execution",
    "transparency",
]

# 预设配置
PERSONA_CONFIGS: dict[HunterPersonaId, dict[str, Any]] = {
    HunterPersonaId.BALANCED: {
        "id": HunterPersonaId.BALANCED.value,
        "name": "全能平衡模式",
        "icon": "⚖️",
        "tagline": "官方标准 8 维黄金配比",
        "description": "均衡考量空投概率、项目叙事、团队履历、代币模型与安全风险，适合日常全面跟进与大多数参与者。",
        "weights": {
            "airdrop_signal": 0.20,
            "narrative_timing": 0.15,
            "team_reputation": 0.15,
            "risk": 0.15,
            "tokenomics": 0.15,
            "execution": 0.10,
            "transparency": 0.05,
            "competition": 0.05,
        },
        "badges": ["官方黄金比例", "稳健防坑", "全赛道兼顾"],
        "key_factors": ["全方位综合表现", "团队信誉与风控平衡", "空投概率与发币时机"],
    },
    HunterPersonaId.ZERO_COST: {
        "id": HunterPersonaId.ZERO_COST.value,
        "name": "零成本测试网党",
        "icon": "🎒",
        "tagline": "0 本金低摩擦，专攻水龙头与测试网",
        "description": "痛恨大额资金质押与 Gas 磨损，重度倾斜公开测试网、免费水龙头领水与清晰明牌任务路径，追求以小博大零资金风险。",
        "weights": {
            "airdrop_signal": 0.28,
            "execution": 0.22,
            "narrative_timing": 0.15,
            "risk": 0.10,
            "transparency": 0.10,
            "team_reputation": 0.05,
            "tokenomics": 0.05,
            "competition": 0.05,
        },
        "badges": ["0 本金测试网", "高频水龙头", "规避流动性质押"],
        "key_factors": ["是否有公开测试网", "水龙头与任务指引健全度", "交互执行确定性与低门槛"],
    },
    HunterPersonaId.WHALE_RESTAKING: {
        "id": HunterPersonaId.WHALE_RESTAKING.value,
        "name": "巨鲸质押生息党",
        "icon": "💎",
        "tagline": "本金绝对安全，主打顶流 VC 领投与高 TVL",
        "description": "拥有充沛闲置资金，追求本金安全、顶级机构 (Paradigm/Pantera/Binance Labs) 背书、真实 TVL 与重质押 (Restaking/LRT) 双重生息收益。",
        "weights": {
            "team_reputation": 0.25,
            "risk": 0.20,
            "tokenomics": 0.20,
            "airdrop_signal": 0.15,
            "execution": 0.10,
            "transparency": 0.05,
            "narrative_timing": 0.03,
            "competition": 0.02,
        },
        "badges": ["Tier-1 顶尖机构", "千万级高 TVL", "严控团队与合约风险"],
        "key_factors": ["领投机构背景与知名度", "资金池与审计风控级别", "代币经济学分配与锁仓安全"],
    },
    HunterPersonaId.HIGH_BETA: {
        "id": HunterPersonaId.HIGH_BETA.value,
        "name": "高弹性叙事追逐者",
        "icon": "⚡",
        "tagline": "风口浪尖抓催化剂，早期布局高爆发 Alpha",
        "description": "敏锐嗅探加密前沿叙事（AI Agent、BTC L2、DePIN、并行 EVM），把握早期红利期，紧跟发币催化剂与爆发期。",
        "weights": {
            "narrative_timing": 0.30,
            "airdrop_signal": 0.25,
            "execution": 0.15,
            "team_reputation": 0.10,
            "tokenomics": 0.10,
            "risk": 0.05,
            "competition": 0.03,
            "transparency": 0.02,
        },
        "badges": ["新兴叙事龙头", "代币 TGE 窗口期", "超额爆发回报"],
        "key_factors": ["叙事热度与窗口期 (Timing)", "代币分配与刺激预期", "早期上线爆发力"],
    },
}


def get_all_personas_metadata() -> list[dict[str, Any]]:
    """获取所有可用角色的元数据列表（用于 API 响应与前端渲染）."""
    return [config for config in PERSONA_CONFIGS.values()]


def parse_sub_scores(sub_scores_raw: Any) -> dict[str, float]:
    """解析子分 JSON 或字典."""
    if not sub_scores_raw:
        return {}
    if isinstance(sub_scores_raw, dict):
        return {k: float(v) for k, v in sub_scores_raw.items() if isinstance(v, (int, float))}
    if isinstance(sub_scores_raw, str):
        try:
            parsed = json.loads(sub_scores_raw)
            if isinstance(parsed, dict):
                return {k: float(v) for k, v in parsed.items() if isinstance(v, (int, float))}
        except (ValueError, TypeError):
            return {}
    return {}


def _extract_signals_and_funding(project_record: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """提取 signals 与 funding 元数据."""
    meta_raw = project_record.get("meta")
    meta: dict[str, Any] = {}
    if isinstance(meta_raw, dict):
        meta = meta_raw
    elif isinstance(meta_raw, str):
        try:
            parsed = json.loads(meta_raw)
            if isinstance(parsed, dict):
                meta = parsed
        except (ValueError, TypeError):
            meta = {}

    signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    funding = meta.get("funding") if isinstance(meta.get("funding"), dict) else {}
    if not funding:
        funding = project_record.get("funding") if isinstance(project_record.get("funding"), dict) else {}

    return signals, funding


def calculate_persona_score(
    project_record: dict[str, Any],
    persona_id: HunterPersonaId | str | None,
) -> dict[str, Any]:
    """根据所选猎人角色计算自适应动态加权分与标签.

    Args:
        project_record: 包含 project 的字段字典（score, sub_scores, meta, signals, funding 等）
        persona_id: 角色 ID（若为空或 balanced，则返回原基准分）

    Returns:
        字典包含:
        - persona_applied: 生效的角色 ID
        - persona_score: 角色加权调整后的最终得分 (0-100)
        - persona_label: 角色自适应标签 (FARM/WATCH/IGNORE)
        - persona_boost_reason: 角色专属加减分理由
        - base_score: 原始基准分
        - score_delta: 角色分与基准分的差值
    """
    base_score = int(project_record.get("score") or 0)
    base_label = str(project_record.get("label") or "WATCH")

    if not persona_id or persona_id == HunterPersonaId.BALANCED.value:
        return {
            "persona_applied": HunterPersonaId.BALANCED.value,
            "persona_score": base_score,
            "persona_label": base_label,
            "persona_boost_reason": "默认官方标准黄金平衡评分",
            "base_score": base_score,
            "score_delta": 0,
        }

    try:
        persona_enum = HunterPersonaId(str(persona_id).lower().strip())
    except ValueError:
        persona_enum = HunterPersonaId.BALANCED

    if persona_enum == HunterPersonaId.BALANCED:
        return {
            "persona_applied": HunterPersonaId.BALANCED.value,
            "persona_score": base_score,
            "persona_label": base_label,
            "persona_boost_reason": "默认官方标准黄金平衡评分",
            "base_score": base_score,
            "score_delta": 0,
        }

    cfg = PERSONA_CONFIGS[persona_enum]
    weights = cfg["weights"]
    sub_scores = parse_sub_scores(project_record.get("sub_scores"))

    # 若没有任何 sub_scores，则以 base_score 为基准计算，避免空子分归零
    if not sub_scores:
        weighted_score = float(base_score)
    else:
        weighted_score = sum(sub_scores.get(k, float(base_score)) * w for k, w in weights.items())

    signals, funding = _extract_signals_and_funding(project_record)
    stage = str(project_record.get("stage") or "").lower()

    bonus = 0.0
    reasons: list[str] = []

    # 1. 零成本测试网党
    if persona_enum == HunterPersonaId.ZERO_COST:
        has_testnet = bool(signals.get("has_testnet") or stage == "testnet")
        has_faucet = bool(signals.get("faucet_url") or signals.get("has_faucet"))
        tvl = float(signals.get("tvl") or 0)

        if has_testnet:
            bonus += 8.0
            reasons.append("具有公开测试网")
        if has_faucet:
            bonus += 3.0
            reasons.append("支持免费水龙头领水")
        if tvl >= 10_000_000 and not has_testnet:
            bonus -= 8.0
            reasons.append("需高资金质押且无测试网路径")

    # 2. 巨鲸质押生息党
    elif persona_enum == HunterPersonaId.WHALE_RESTAKING:
        funding_tier = str(funding.get("funding_tier") or "").lower()
        funding_usd = float(funding.get("funding_total_usd") or 0)
        tvl = float(signals.get("tvl") or 0)
        risk_score = sub_scores.get("risk", 70.0)

        is_tier1 = "tier-1" in funding_tier or "tier1" in funding_tier or "tier 1" in funding_tier
        is_large_funding = funding_usd >= 10_000_000
        is_high_tvl = tvl >= 5_000_000

        if is_tier1 or is_large_funding or is_high_tvl:
            bonus += 8.0
            reasons.append("顶级机构参投/高资金沉淀安全保障")
        if risk_score < 45.0:
            bonus -= 10.0
            reasons.append("团队风控评级偏低，不满足大资金安全要求")

    # 3. 高弹性叙事追逐者
    elif persona_enum == HunterPersonaId.HIGH_BETA:
        timing_score = sub_scores.get("narrative_timing", 60.0)
        is_early_stage = stage in ("early", "testnet", "seed", "concept")

        if timing_score >= 75.0 and is_early_stage:
            bonus += 8.0
            reasons.append("前沿风口极早期阶段，爆发弹性高")
        elif timing_score <= 45.0:
            bonus -= 6.0
            reasons.append("叙事热度过峰进入平缓期")

    final_score = int(round(min(100.0, max(0.0, weighted_score + bonus))))

    # 根据重算后的分数推导标签
    if final_score >= 65:
        final_label = "FARM"
    elif final_score >= 50:
        final_label = "WATCH"
    else:
        final_label = "IGNORE"

    boost_summary = "；".join(reasons) if reasons else "基于专属权重矩阵动态自适应调整"

    return {
        "persona_applied": persona_enum.value,
        "persona_score": final_score,
        "persona_label": final_label,
        "persona_boost_reason": boost_summary,
        "base_score": base_score,
        "score_delta": final_score - base_score,
    }
