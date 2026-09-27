"""Smart Money Radar & Social Heat Service (聪明钱监控目标与社交热度榜).

诚实口径（2026-09-23 审计，docs/EXPANSION_AUDIT_REPORT.md）：

此服务历史上返回**编造的巨鲸动态**（「Vitalik 向 Farcaster 签名信令 12 小时前」
「Paradigm 存入 500 stETH」等）与硬编码的社交增速数组，全部以实时口吻呈现。
巨鲸链上监控需要真实的链上数据供给（索引器/Alchemy 事件流等），在没有数据源
之前，如实表现为 0 条动态，而不是编故事：

- ``smart_money_activities``：**恒为空列表**——占位形态保留，待接入真实
  数据源后填充。
- ``tracked_whales``：公开、可验证的知名地址白名单（Vitalik 等公开人物地址
  是链上事实），性质是静态知识清单，不是动态情报。
- ``social_velocity_spikes``：返回数据库中的真实高分项目，但**不再编造增速
  百分比**——排序与「热度榜」位置直接采用项目综合评分（真实数据），缺失的
  社交增速字段如实为 ``None`` 并在 ``note`` 中说明。
"""

from __future__ import annotations

from typing import Any

import structlog

from app.db import connection_scope, dict_from_row

logger = structlog.get_logger(__name__)

# 公开可验证的知名地址白名单（静态知识，非动态情报）。
# 仅收录地址本身是公开事实的对象；任何「该地址最近做了什么」的描述
# 在接入真实链上数据源之前一律不出。
TRACKED_WHALE_PROFILES: list[dict[str, Any]] = [
    {
        "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",
        "label": "Vitalik Buterin (以太坊创始人)",
        "tier": "public_figure",
    },
]


def get_smart_money_and_social_feed() -> dict[str, Any]:
    """返回聪明钱监控目标清单与基于真实评分的项目热度榜.

    老版本在此返回编造的巨鲸动态与假增速，已按诚实口径清理：
    动态为空、增速不编造，榜单排序使用真实的项目综合评分。
    """
    # 1. 巨鲸动态：无真实数据源，如实为空（占位形态待接入后填充）
    activities: list[dict[str, Any]] = []

    # 2. 热度榜：真实高分项目（评分是真实计算），但不编造社交增速
    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT id, name, sector, score, label, stage, narrative_json
            FROM projects
            WHERE (source != 'historical_backfill' OR source IS NULL)
            ORDER BY score DESC LIMIT 8
            """
        ).fetchall()
        projects = [dict_from_row(r) for r in rows]

    social_spikes = []
    for p in projects:
        social_spikes.append(
            {
                "project_id": p["id"],
                "project_name": p["name"],
                "sector": p.get("sector") or "Web3",
                "score": p.get("score"),
                "label": p.get("label"),
                # 社交增速需要真实社交数据源；接入前如实为 None，不编数
                "social_velocity_growth_pct": None,
                # 榜单排序依据 = 项目综合评分（真实数据）
                "velocity_rank_basis": "project_score",
                "primary_narrative": None,
            }
        )

    return {
        "ok": True,
        "smart_money_activities": activities,
        "tracked_whales": TRACKED_WHALE_PROFILES,
        "social_velocity_spikes": social_spikes,
        "tracked_whales_count": len(TRACKED_WHALE_PROFILES),
    }
