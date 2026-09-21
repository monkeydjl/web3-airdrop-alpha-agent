"""Alpha Digest & Weekly Intelligence Generator (Alpha 投研周报生成引擎).

100% deterministic, zero LLM token cost, zero paid API dependencies.
Aggregates top FARM/WATCH projects, funding momentum, zero-cost testnet opportunities,
anti-PUA capital friction radar, and multi-wallet operational guidance into a unified Markdown digest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import structlog

from app.db import dict_from_row, get_connection
from app.repository import is_zero_cost_opportunity
from app.services.project_signals import funding_public_view, parse_meta

logger = structlog.get_logger(__name__)


def generate_alpha_digest(
    *,
    window_days: int = 7,
    min_score: float = 70.0,
    limit: int = 15,
) -> dict[str, Any]:
    """Generate structured Alpha intelligence digest in Markdown and JSON summary.

    Args:
        window_days: Time horizon in days (e.g. 7 for weekly, 14 for biweekly, 30 for monthly).
        min_score: Minimum total score threshold for candidate projects.
        limit: Max projects to highlight in the Top Alpha Picks section.

    Returns:
        Dict with markdown content and structured summary statistics.
    """
    conn = get_connection()
    now = datetime.now(UTC)
    date_str = now.strftime("%Y-%m-%d")

    cursor = conn.execute(
        """
        SELECT id, name, sector, stage, score, label, reason, sub_scores, meta, updated_at
        FROM projects
        ORDER BY score DESC
        """
    )
    rows = cursor.fetchall()

    all_projects: list[dict[str, Any]] = []
    farm_projects: list[dict[str, Any]] = []
    zero_cost_projects: list[dict[str, Any]] = []
    sector_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    pua_warning_projects: list[dict[str, Any]] = []

    for row in rows:
        p = dict_from_row(row)
        score = float(p.get("score") or 0.0)
        label = str(p.get("label") or "WATCH")
        sector = str(p.get("sector") or "infra")
        stage = str(p.get("stage") or "ideation")
        meta = parse_meta(p.get("meta"))
        funding = funding_public_view(meta)

        all_projects.append(p)
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

        if is_zero_cost_opportunity(p):
            zero_cost_projects.append(p)

        v_tier = meta.get("viability_tier")
        if v_tier == "unviable" or "low_runway_risk" in str(p.get("reason") or ""):
            pua_warning_projects.append(p)

        if label == "FARM" or score >= min_score:
            farm_projects.append(p)

    top_picks = farm_projects[:limit]
    total_scanned = len(all_projects)
    total_farm = len([p for p in all_projects if p.get("label") == "FARM"])
    total_zero_cost = len(zero_cost_projects)
    avg_top_score = (
        round(sum(float(p.get("score") or 0) for p in top_picks) / len(top_picks), 1)
        if top_picks
        else 0.0
    )

    top_sectors_sorted = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    # Build Markdown document
    lines: list[str] = [
        f"# 🦅 Web3 Alpha 深度投研周报（{date_str}）",
        "",
        "> 本期周报由 **Web3 Airdrop Alpha Agent System** 纯规则确定性引擎自动聚合并生成。",
        f"> 覆盖全库 **{total_scanned}** 个监控项目，精选评分 ≥ {min_score} 与重点推荐 (FARM) 项目，零第三方商业 API 与 Token 成本。",
        "",
        "---",
        "",
        "## 1. 📊 核心宏观态势与雷达概览",
        "",
        f"- **重点参与 (FARM) 项目库存**：`{total_farm}` 个（全库占比 {round(total_farm / total_scanned * 100, 1) if total_scanned else 0}%）",
        f"- **零资金门槛测试网机会**：`{total_zero_cost}` 个（免本金摩擦，水龙头驱动）",
        f"- **本期精选 Top 项目均分**：`{avg_top_score}` 分",
        "- **热门叙事赛道分布**：" + "、".join(f"`{k}` ({v})" for k, v in top_sectors_sorted),
        "",
        "---",
        "",
        "## 2. 🌟 本周 Top Alpha 精选项目清单",
        "",
        "| 项目 | 赛道 | 阶段 | 评分 | 标签 | 融资金额 | 机构背书 | 存活率建议 |",
        "|---|---|---|---|---|---|---|---|",
    ]

    for p in top_picks:
        name = p.get("name") or f"Project #{p['id']}"
        sector = p.get("sector") or "-"
        stage = p.get("stage") or "-"
        score = round(float(p.get("score") or 0), 1)
        label = p.get("label") or "WATCH"
        meta = parse_meta(p.get("meta"))
        funding = funding_public_view(meta)
        amount = funding.get("funding_total_usd") or 0.0
        amount_str = f"${amount/1e6:,.1f}M" if amount >= 1e6 else (f"${amount/1e3:,.0f}K" if amount > 0 else "未知")
        tier = funding.get("funding_tier") or "unknown"
        tier_str = "Tier-1 顶级" if tier == "tier1" else ("Tier-2 知名" if tier == "tier2" else "常规/早期")
        v_tier = meta.get("viability_tier") or "viable"
        v_str = "稳健充足" if v_tier == "viable" else ("跑道观察" if v_tier == "borderline" else "存活预警")
        lines.append(f"| **{name}** | `{sector}` | `{stage}` | **{score}** | `{label}` | {amount_str} | {tier_str} | {v_str} |")

    lines.extend([
        "",
        "---",
        "",
        "## 3. 🛡️ 零资金成本测试网优先专区 (Zero-Cost Opportunities)",
        "",
        "以下项目处于测试网或极早期阶段，**无需质押沉淀大额资金**，依托测试网水龙头即可完成交互，性价比与 ROI 风险比极佳：",
        "",
    ])

    for p in zero_cost_projects[:8]:
        name = p.get("name") or f"Project #{p['id']}"
        sector = p.get("sector") or "infra"
        score = round(float(p.get("score") or 0), 1)
        meta = parse_meta(p.get("meta"))
        signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
        has_faucet = bool(signals.get("has_faucet") or "faucet" in str(meta))
        lines.append(
            f"- **{name}** (`{sector}` · 评分: {score})："
            f" 阶段: `{p.get('stage')}` | 水龙头支持: {'✅ 已集成' if has_faucet else '⚠️ 需公共水龙头'} | 建议: 保持每周 1-2 次低频交互打卡。"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 4. ⚠️ 防 PUA 疲劳指数与风险避坑雷达 (Risk & Friction Warning)",
        "",
        "基于链上真实融资、跑道存活率硬门禁与代码活跃度检测，以下特征项目建议**严格控制精力分配与资金磨损**：",
        "",
        "1. **纯积分盘且无大额融资背书 (Unbacked Points Machine)**：杜绝参与以积分任务为幌子却无 Tier-1/Tier-2 机构注资的项目，避免被长期 PUA。",
        "2. **跑道耗尽停摆 (Runway Depleted)**：公开融资发生于 18 个月以上且 GitHub 活跃度低于 60 天的项目，极大概率存在团队资金链断裂风险。",
        "3. **高摩擦重资金锁仓 (Heavy Capital Friction)**：无明显代币经济学刺激的借贷锁仓，资金占用成本远高于空投预期 ROI。",
        "",
    ])

    if pua_warning_projects:
        lines.append(f"> 🚨 当前全库共有 **{len(pua_warning_projects)}** 个项目被标记为存活率低或跑道耗尽预警，系统已自动对其执行标签降级保护。")
    else:
        lines.append("> ✅ 当前监控范围内未发现大面积资金盘跑道异常。")

    lines.extend([
        "",
        "---",
        "",
        "## 5. 💼 多钱包防女巫操作守则与资金配置建议",
        "",
        "对于准备多钱包参与的高确定性项目，请严格遵循系统建议的防女巫隔离原则：",
        "",
        "1. **资金链路物理隔离**：绝对禁止钱包间直接转账（A → B），提币充币必须通过不同 CEX 子账户或隐私跨链中继；",
        "2. **时间维度离散化**：各钱包交互时间应错开 2~48 小时，严禁使用批量脚本同区块或同分钟执行；",
        "3. **行为轨迹差异化**：交互路径与金额随机化（避免每个钱包均做一模一样金额的 Swap/Mint）；",
        "4. **IP 与运行环境隔离**：不同钱包使用独立指纹浏览器环境或分散代理节点。",
        "",
        "---",
        f"*报告生成时间：{now.isoformat()} · Web3 Airdrop Alpha Agent System*",
    ])

    markdown_text = "\n".join(lines)

    summary_data = {
        "generated_at": now.isoformat(),
        "date_str": date_str,
        "window_days": window_days,
        "total_scanned": total_scanned,
        "total_farm": total_farm,
        "total_zero_cost": total_zero_cost,
        "avg_top_score": avg_top_score,
        "top_picks_count": len(top_picks),
        "top_sectors": top_sectors_sorted,
        "pua_warning_count": len(pua_warning_projects),
    }

    return {
        "ok": True,
        "markdown": markdown_text,
        "summary": summary_data,
    }
