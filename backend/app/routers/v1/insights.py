"""Insights Endpoint - 聚合洞察数据.

GET /api/v1/insights
- 汇总全部已评分项目的聚合指标
- 为 Dashboard Insights 页提供数据

Reference:
- docs/FRONTEND_SPEC.md §3.3 Insight
"""

import json
from collections import defaultdict
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from app.db import get_connection
from app.repository import ProjectRepository

router = APIRouter(tags=["insights"])


class InsightsResponse(BaseModel):
    """洞察聚合响应。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "total_projects": 12,
                    "label_counts": {"FARM": 3, "WATCH": 5, "IGNORE": 4},
                    "sector_counts": {"L2": 4, "DeFi": 3, "Gaming": 2},
                    "hottest_narratives": [
                        {
                            "sector": "L2",
                            "project_count": 4,
                            "avg_heat_score": 0.82,
                            "trend": "up",
                        }
                    ],
                    "risky_teams": [
                        {
                            "id": "anon-001",
                            "name": "AnonProject",
                            "sector": "DeFi",
                            "risk_level": "high",
                            "team_score": 0.25,
                            "flags": ["anonymous team"],
                        }
                    ],
                },
            }
        }
    )

    ok: bool = Field(True, description="请求是否成功")
    data: dict = Field(..., description="聚合数据")


def _safe_json(value: Any) -> dict:
    """安全解析 JSON 字段。"""
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}


@router.get(
    "/insights",
    response_model=InsightsResponse,
    summary="聚合洞察数据",
    description="返回项目 label/sector 分布、最热叙事排行和高风险团队列表。",
)
def get_insights() -> InsightsResponse:
    """获取聚合洞察数据。

    Returns:
        InsightsResponse 包含各类聚合指标
    """
    # 单条连接完成全部聚合：分组计数交给数据库，只把窄投影搬进 Python
    conn = get_connection()
    try:
        repo = ProjectRepository(conn)
        raw_label_counts = repo.aggregate_counts("label")
        raw_sector_counts = repo.aggregate_counts("sector")
        projects = repo.list_insight_rows()
    finally:
        conn.close()

    # 归一空值分桶，保持与旧的 Python 端聚合完全一致的输出
    label_counts: defaultdict[str, int] = defaultdict(int)
    for bucket, n in raw_label_counts.items():
        label_counts[bucket or "UNRATED"] += n
    sector_counts: defaultdict[str, int] = defaultdict(int)
    for bucket, n in raw_sector_counts.items():
        sector_counts[bucket or "Unknown"] += n

    sector_heat = defaultdict(list)
    risky_teams = []

    for project in projects:
        sector = project.get("sector") or "Unknown"

        narrative = _safe_json(project.get("narrative_json"))
        heat_score = narrative.get("heat_score")
        if isinstance(heat_score, (int, float)):
            sector_heat[sector].append(heat_score)

        team = _safe_json(project.get("team_json"))
        team_score = team.get("team_score")
        if isinstance(team_score, (int, float)):
            risk_level = "high" if team_score < 0.4 else ("medium" if team_score <= 0.7 else "low")
        else:
            risk_level = None

        if risk_level in ("high", "medium"):
            flags = team.get("team_flags") or []
            if not isinstance(flags, list):
                flags = []
            risky_teams.append(
                {
                    "id": project.get("id"),
                    "name": project.get("name"),
                    "sector": sector,
                    "risk_level": risk_level,
                    "team_score": team_score,
                    "flags": flags,
                }
            )

    hottest = []
    for sector, heats in sector_heat.items():
        avg = sum(heats) / len(heats)
        trend = "up" if avg >= 0.7 else ("down" if avg < 0.4 else "flat")
        hottest.append(
            {
                "sector": sector,
                "project_count": len(heats),
                "avg_heat_score": round(avg, 2),
                "trend": trend,
            }
        )
    hottest.sort(key=lambda x: (x["avg_heat_score"], x["project_count"]), reverse=True)

    risky_teams.sort(key=lambda x: (0 if x["risk_level"] == "high" else 1, x["team_score"] or 0.5))

    return InsightsResponse(
        ok=True,
        data={
            "total_projects": len(projects),
            "label_counts": dict(label_counts),
            "sector_counts": dict(sector_counts),
            "hottest_narratives": hottest,
            "risky_teams": risky_teams,
        },
    )
