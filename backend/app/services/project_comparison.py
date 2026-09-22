"""Project Comparison & Head-to-Head PK Engine (多项目竞品多维对比与决策矩阵).

支持 2~3 个项目的 8 维指标标准化提取、雷达图对齐计算与差异化策略裁决。
100% 确定性算法，零外部商业 API 成本。
"""

from __future__ import annotations

import json
from typing import Any

from app.db import dict_from_row, get_connection

DIMENSIONS = [
    {"key": "narrative", "name": "叙事热度", "description": "赛道风口契合度与行业讨论度"},
    {"key": "team", "name": "团队实力", "description": "团队公开度、一线 VC 背书与历史成功退出"},
    {"key": "funding", "name": "融资金额", "description": "公开融资金额与资本跑道充裕度"},
    {"key": "execution", "name": "开发执行", "description": "GitHub 提交活跃度与测试网迭代速度"},
    {"key": "tokenomics", "name": "代币预期", "description": "代币分配公平性与空投预期释放比例"},
    {"key": "sybil_barrier", "name": "防女巫度", "description": "防女巫洗劫难度，高壁垒保护真实猎人"},
    {"key": "viability", "name": "项目存活", "description": "抗跑路风险、资金库健康度与长期发展"},
    {"key": "capital_eff", "name": "资金效率", "description": "低资金低 Gas 磨损换取高积分回报"},
]


def _safe_json_loads(val: Any) -> Any:
    if isinstance(val, (dict, list)):
        return val
    if not val:
        return {}
    try:
        return json.loads(val)
    except Exception:
        return {}


def compare_projects(project_ids: list[str]) -> dict[str, Any]:
    """对选定的 2~3 个项目进行 8 维深度量化对比与策略裁决."""
    if not project_ids:
        raise ValueError("At least one project ID must be provided")

    clean_ids = [pid.strip() for pid in project_ids if pid.strip()][:3]

    conn = get_connection()
    try:
        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT id, name, sector, stage, score, label, confidence,
                   sub_scores, reason, meta, narrative_json, source, url
            FROM projects
            WHERE id IN ({placeholders})
            """,
            clean_ids,
        ).fetchall()
        projects = [dict_from_row(r) for r in rows]
    finally:
        conn.close()

    if not projects:
        raise ValueError(f"No projects found matching IDs: {clean_ids}")

    # 规范化各项目各维度评分 (0 - 100)
    project_scores_map = {}
    for p in projects:
        sub = _safe_json_loads(p.get("sub_scores"))
        meta = _safe_json_loads(p.get("meta"))
        signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}

        # 8 维计算
        narrative_val = float(sub.get("narrative") or 70.0)
        team_val = float(sub.get("team") or 65.0)
        funding_val = float(sub.get("funding") or 60.0)
        exec_val = float(sub.get("execution") or 65.0)
        token_val = float(sub.get("tokenomics") or 70.0)
        sybil_val = float(sub.get("sybil_resistance") or 75.0)
        viability_val = float(sub.get("viability") or 80.0)
        cap_val = float(sub.get("capital_efficiency") or 70.0)

        # 结合 signals 进行精细微调
        funding_total = signals.get("funding_total_usd") or signals.get("total_raised_usd")
        if funding_total and float(funding_total) > 50_000_000:
            funding_val = min(98.0, funding_val + 15.0)

        if signals.get("has_testnet"):
            cap_val = min(95.0, cap_val + 10.0)

        project_scores_map[p["id"]] = {
            "narrative": round(narrative_val, 1),
            "team": round(team_val, 1),
            "funding": round(funding_val, 1),
            "execution": round(exec_val, 1),
            "tokenomics": round(token_val, 1),
            "sybil_barrier": round(sybil_val, 1),
            "viability": round(viability_val, 1),
            "capital_eff": round(cap_val, 1),
        }

    # 计算各维度雷达轴
    radar_axes = []
    for dim in DIMENSIONS:
        k = dim["key"]
        axis_entry: dict[str, Any] = {
            "key": k,
            "name": dim["name"],
            "description": dim["description"],
            "values": {},
        }
        for p in projects:
            axis_entry["values"][p["id"]] = project_scores_map[p["id"]][k]
        radar_axes.append(axis_entry)

    # 计算胜出者与裁决 (Verdict)
    sorted_by_score = sorted(projects, key=lambda p: float(p.get("score") or 0), reverse=True)
    winner_overall = sorted_by_score[0]

    # 针对小资金 (注重 capital_eff + has_testnet)
    best_low_capital = max(
        projects,
        key=lambda p: project_scores_map[p["id"]]["capital_eff"] + project_scores_map[p["id"]]["narrative"],
    )

    # 针对大资金 (注重 funding + viability + team)
    best_whale_staking = max(
        projects,
        key=lambda p: project_scores_map[p["id"]]["funding"] + project_scores_map[p["id"]]["viability"],
    )

    # 生成差异化对比要点
    tradeoffs = []
    if len(projects) >= 2:
        p1, p2 = projects[0], projects[1]
        p1_scores = project_scores_map[p1["id"]]
        p2_scores = project_scores_map[p2["id"]]

        if p1_scores["funding"] > p2_scores["funding"] + 10:
            tradeoffs.append(f"【融资优势】{p1['name']} 融资更强劲，资金跑道更充裕；而 {p2['name']} 更依赖社区驱动。")
        elif p2_scores["funding"] > p1_scores["funding"] + 10:
            tradeoffs.append(f"【融资优势】{p2['name']} 获顶级机构重注，抗风险能力显著优于 {p1['name']}。")

        if p1_scores["capital_eff"] > p2_scores["capital_eff"] + 10:
            tradeoffs.append(f"【参与门槛】{p1['name']} 资金门槛更低，更适合多号轻资产刷取。")
        elif p2_scores["capital_eff"] > p1_scores["capital_eff"] + 10:
            tradeoffs.append(f"【参与门槛】{p2['name']} 支持测试网或低摩擦交互，散户投入产出比更优。")

        tradeoffs.append(
            f"【战术建议】若资金充裕首选 {best_whale_staking['name']}；若追求高杠杆散户赔率首选 {best_low_capital['name']}。"
        )

    return {
        "ok": True,
        "projects": [
            {
                "id": p["id"],
                "name": p["name"],
                "sector": p.get("sector") or "Web3",
                "stage": p.get("stage") or "mainnet",
                "score": p.get("score") or 0,
                "label": p.get("label") or "WATCH",
                "url": p.get("url") or "",
                "dimension_scores": project_scores_map[p["id"]],
            }
            for p in projects
        ],
        "dimensions": DIMENSIONS,
        "radar_axes": radar_axes,
        "verdict": {
            "winner_overall_id": winner_overall["id"],
            "winner_overall_name": winner_overall["name"],
            "best_for_low_capital_id": best_low_capital["id"],
            "best_for_low_capital_name": best_low_capital["name"],
            "best_for_whale_staking_id": best_whale_staking["id"],
            "best_for_whale_staking_name": best_whale_staking["name"],
            "tradeoffs": tradeoffs,
        },
    }
