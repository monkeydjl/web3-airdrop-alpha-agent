"""Alpha Dossier Generator.

Aggregates:
1. Basic fundamentals & narrative timing
2. Funding quality & Runway viability gate
3. Anti-PUA fatigue index & capital friction advisory
4. Multi-source free signal consensus
5. Multi-wallet sybil-resistance participation guide
6. Prioritized participation tasks & testnet faucets

Outputs a professional, publication-ready Markdown research dossier + JSON summary.
100% deterministic facts, 0 commercial API costs, 0 LLM token spend.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.repository import ProjectRepository
from app.services.anti_pua import (
    calculate_fatigue_index,
    classify_capital_friction_tier,
    evaluate_exit_advisory,
)
from app.services.faucet_registry import list_faucets_with_status
from app.services.multi_wallet_strategy import generate_multi_wallet_strategy
from app.services.participation_tasks import generate_participation_tasks
from app.services.signal_correlation import correlate_signals_for_project
from app.services.viability_gate import evaluate_project_viability

logger = structlog.get_logger(__name__)


def _format_usd(val: Any) -> str:
    try:
        n = float(val)
        if n <= 0:
            return "未公开 / 0"
        if n >= 1_000_000_000:
            return f"${n / 1_000_000_000:.2f}B"
        if n >= 1_000_000:
            return f"${n / 1_000_000:.2f}M"
        if n >= 1_000:
            return f"${n / 1_000:.1f}K"
        return f"${n:,.2f}"
    except (ValueError, TypeError):
        return "未公开"


def generate_alpha_dossier(project_id: str) -> dict[str, Any]:
    """Generate a comprehensive Alpha Deep Research Dossier for a given project."""
    repo = ProjectRepository()
    row = repo.get_by_id(project_id)
    if not row:
        raise ValueError(f"Project not found: {project_id}")

    name = row.get("name") or "未命名项目"
    url = row.get("url") or ""
    sector = row.get("sector") or "unknown"
    stage = row.get("stage") or "mainnet"
    score = row.get("score") or 0
    label = (row.get("label") or "WATCH").upper()
    confidence = float(row.get("confidence") or 0.5)

    def _parse_field(val: Any) -> Any:
        if isinstance(val, (dict, list)):
            return val
        if not val:
            return None
        try:
            return json.loads(val)
        except Exception:
            return None

    raw_reasons = _parse_field(row.get("reason"))
    reasons = raw_reasons if isinstance(raw_reasons, list) else ([str(raw_reasons)] if raw_reasons else [])
    raw_sub = _parse_field(row.get("sub_scores"))
    sub_scores = raw_sub if isinstance(raw_sub, dict) else {}

    # 1. 融资与背书
    raw_meta = _parse_field(row.get("meta"))
    meta = raw_meta if isinstance(raw_meta, dict) else {}
    signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    funding_total = signals.get("funding_total_usd") or signals.get("total_raised_usd")
    funding_rounds = signals.get("funding_rounds") or 0
    funding_tier = signals.get("funding_tier") or "unrated"
    funding_investors = signals.get("funding_investors") or []
    funding_last_date = signals.get("funding_last_date") or ""

    # 2. 存活率硬门禁
    viability = evaluate_project_viability(
        funding_total_usd=float(funding_total) if funding_total is not None else None,
        funding_tier=funding_tier,
        funding_rounds=funding_rounds,
        funding_last_date=funding_last_date,
        funding_investors=funding_investors,
        has_points_program=bool(signals.get("has_points_program")),
        stage=stage,
    )
    v_tier = viability.get("tier", "borderline")
    v_tier_zh = {
        "viable": "🟢 资金充裕 / 背书强劲",
        "borderline": "🟡 跑道观察期 / 早期探索",
        "unviable": "🔴 存活预警 / 高危跑路风险",
    }.get(v_tier, v_tier)
    v_advisory = viability.get("advisory") or "暂无存活预警"

    # 3. 防 PUA 与资本摩擦
    farming_days = signals.get("farming_days") or 0
    duration_months = float(farming_days) / 30.0 if farming_days else 0.0
    season_count = int(signals.get("season_count") or 1)
    tge_transparency = str(signals.get("tge_transparency") or "unannounced")
    lockup_days = int(signals.get("lockup_days") or 0)
    fatigue = calculate_fatigue_index(
        duration_months=duration_months,
        season_count=season_count,
        tge_transparency=tge_transparency,
        lockup_days=lockup_days,
    )

    gas_spent = signals.get("gas_spent_usd")
    tvl_dep = signals.get("tvl_deposited_usd")
    friction_tier = classify_capital_friction_tier(
        has_testnet=bool(signals.get("has_testnet")),
        hard_cost_usd=float(gas_spent) if gas_spent is not None else None,
        capital_at_risk_usd=float(tvl_dep) if tvl_dep is not None else None,
    )
    friction_zh = {
        "zero_cost": "零资金成本 (仅交互/测试网)",
        "low_cost": "低成本摩擦 (微量 Gas)",
        "medium_cost": "中等摩擦 (小额质押/交易摩擦)",
        "heavy_capital": "重资本锁仓 (高摩擦/重流动性)",
    }.get(friction_tier, friction_tier)

    exit_adv = evaluate_exit_advisory(
        github_inactive_days=signals.get("github_inactive_days"),
    )
    if exit_adv.get("active"):
        exit_reasons = " / ".join(exit_adv.get("reasons_zh", ()))
        exit_adv_zh = f"⚠️ 恶化预警 ({exit_reasons})"
    else:
        exit_adv_zh = "正常交互 (未触发恶化预警)"

    # 4. 多源共识印证
    consensus = correlate_signals_for_project(project_id=project_id)
    consensus_tier_zh = consensus.get("consensus_tier_zh") or "单源情报"
    source_count = consensus.get("source_count") or 1
    sources_list = consensus.get("sources") or [row.get("source") or "未知"]
    has_testnet_consensus = consensus.get("has_testnet_consensus", False)
    boost_pct = int((consensus.get("free_alpha_boost") or 0.0) * 100)

    # 5. 多钱包防女巫策略
    wallet_strat = generate_multi_wallet_strategy(row)
    wallet_strat_dict = wallet_strat.to_dict()

    # 6. 保姆级交互清单与水龙头
    tasks_dict = generate_participation_tasks(row)
    tasks = tasks_dict.get("tasks") or []

    # 推荐水龙头
    faucets = []
    if "testnet" in stage.lower() or bool(signals.get("has_testnet")):
        faucets = list_faucets_with_status()

    # 构建 Markdown 报告
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    md_lines = [
        f"# 🎯 Alpha 深度投研研报: {name}",
        "",
        f"> **生成时间**: {now_str} | **评级**: `{label}` | **综合评分**: `{score} 分` | **置信度**: `{int(confidence * 100)}%`",
        f"> **行动结论**: {'🚀 优先参与 (优质标的)' if label == 'FARM' else ('👀 重点观察 (关注时机)' if label == 'WATCH' else '🛑 建议忽略 (高风险/已发币)')}",
        "",
        "---",
        "",
        "## 1. 📌 项目基本面与叙事定位",
        f"- **项目名称**: {name}",
        f"- **所属赛道**: `{sector}`",
        f"- **部署阶段**: `{stage}`",
        f"- **官方网站**: [{url}]({url})" if url else "- **官方网站**: 未提供",
        "- **核心评分理由**:",
    ]
    for r in reasons[:5]:
        md_lines.append(f"  - {r}")

    md_lines.extend(
        [
            "",
            "---",
            "",
            "## 2. 💰 机构背书与跑道存活率评估",
            f"- **公开融资金额**: `{_format_usd(funding_total)}`",
            f"- **融资轮次**: `{funding_rounds} 轮`",
            f"- **机构梯队**: `Tier-{funding_tier.replace('tier_', '') if 'tier_' in funding_tier else funding_tier}`",
            f"- **参投机构**: {', '.join(funding_investors[:10]) if funding_investors else '未公开知名机构'}",
            f"- **最新融资日期**: `{funding_last_date or '未知'}`",
            f"- **存活门禁评级**: **{v_tier_zh}**",
            f"- **跑道与生存诊断**: {v_advisory}",
            "",
            "---",
            "",
            "## 3. 🛡️ 防 PUA 疲劳指数与资本摩擦分析",
            f"- **PUA 疲劳指数**: **`{fatigue:.2f}`** / 1.00 ({'极高风险' if fatigue >= 0.7 else ('中度疲劳' if fatigue >= 0.4 else '健康')})",
            f"- **资本摩擦等级**: **{friction_zh}**",
            f"- **止损退出评估**: **{exit_adv_zh}**",
        ]
    )

    if exit_adv.get("reasons"):
        md_lines.append("- **恶化预警指标**:")
        for er in exit_adv["reasons"]:
            md_lines.append(f"  - ⚠️ {er}")

    md_lines.extend(
        [
            "",
            "---",
            "",
            "## 4. 🎯 多源免费情报共识印证",
            f"- **情报共识等级**: **{consensus_tier_zh}** (来自 `{source_count}` 个独立渠道)",
            f"- **覆盖情报源**: {', '.join([f'`{s}`' for s in sources_list])}",
            f"- **测试网跨源印证**: {'✅ 已多源确认真实存在' if has_testnet_consensus else 'ℹ️ 单源或尚未明确'}",
            f"- **Alpha 确定性加成**: `+{boost_pct}%`",
            "",
            "---",
            "",
            "## 5. 💼 多钱包防女巫参与指南",
            f"- **推荐参与架构**: **{wallet_strat.tier_zh}** ({wallet_strat.recommended_wallets_optimal} 个隔离钱包)",
            f"- **总资金预算预估**: `${wallet_strat.total_capital_usd_min:.0f} ~ ${wallet_strat.total_capital_usd_max:.0f}`",
            f"- **每周时间投入**: `{wallet_strat.total_weekly_hours:.1f} 小时/周`",
            "- **四项防女巫隔离准则**:",
            "  1. 🚫 **资金零关联**: 所有交互钱包间绝对禁止链上互转，提币必须使用 CEX 独立子账户。",
            "  2. ⏳ **时间与金额离散化**: 各钱包交互时间随机间隔数小时或数天，金额保持随机小数位。",
            "  3. 🔀 **链上轨迹差异化**: 混合不同 DEX、借贷与合约交互路由，拒绝镜像脚本特征。",
            "  4. 🛡️ **环境与指纹隔离**: 配合防关联指纹浏览器与独立代理节点，严禁同一 IP/设备并发多登。",
            "",
            "---",
            "",
            "## 6. 📋 保姆级交互清单与水龙头指引",
        ]
    )

    if faucets:
        md_lines.append("### 🚰 推荐免 Key 公共测试网水龙头:")
        for f in faucets[:4]:
            f_name = f.get("name") if isinstance(f, dict) else getattr(f, "name", "")
            f_chain = (f.get("chain_name") or f.get("chain")) if isinstance(f, dict) else getattr(f, "chain_name", "")
            f_url = f.get("url") if isinstance(f, dict) else getattr(f, "url", "")
            f_cd = f.get("cooldown_hours") if isinstance(f, dict) else getattr(f, "cooldown_hours", 24)
            md_lines.append(f"- **{f_name}** (`{f_chain}`): [{f_url}]({f_url}) · 冷却 `{f_cd}h`")
        md_lines.append("")

    md_lines.append("### 📌 交互任务清单 (按执行优先级排序):")
    md_lines.append("| 优先级 | 分类 | 任务内容 | 投入成本 | 行动提示 |")
    md_lines.append("| :--- | :--- | :--- | :--- | :--- |")
    for t in tasks[:8]:
        prio = f"P{t.get('priority', 3)}"
        cat = t.get("category_zh") or t.get("category")
        title = t.get("title")
        effort = t.get("effort_zh") or t.get("effort")
        hint = t.get("action_hint") or t.get("why") or "—"
        md_lines.append(f"| `{prio}` | {cat} | **{title}** | {effort} | {hint} |")

    md_lines.extend(
        [
            "",
            "---",
            "*免责声明：本研报仅供交互策略与风险防范参考，不构成任何投资建议。严守安全红线，严禁在未确认标的上投入大额流动性。*",
        ]
    )

    dossier_markdown = "\n".join(md_lines)

    summary = {
        "project_id": project_id,
        "name": name,
        "score": score,
        "label": label,
        "viability_tier": v_tier,
        "fatigue_index": round(fatigue, 2),
        "friction_tier": friction_tier,
        "runway_months": viability.get("runway_months"),
        "consensus_tier": consensus.get("consensus_tier"),
        "consensus_signals": source_count,
        "multi_wallet_tier": wallet_strat.tier,
        "recommended_wallets": wallet_strat.recommended_wallets_optimal,
        "tasks_count": len(tasks),
    }

    return {
        "project_id": project_id,
        "project_name": name,
        "generated_at": now_str,
        "markdown": dossier_markdown,
        "summary": summary,
    }

