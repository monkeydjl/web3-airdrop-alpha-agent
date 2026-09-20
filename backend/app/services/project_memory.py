"""Project Evolution Memory service (Roadmap §24.3 / W12-02).

Tracks project score trajectory, stage progression, label changes, and volatility across runs,
providing analytical summaries and LLM context.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any

import structlog

from app.db import DbConnection, get_connection
from app.repositories.v2 import ProjectHistoryRepository
from app.repository import ProjectRepository

logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class StageTransition:
    from_stage: str
    to_stage: str
    timestamp: str


@dataclass(frozen=True)
class TimelinePoint:
    snapshot_id: int
    run_id: str
    score: int | None
    label: str | None
    stage: str | None
    weight_version: str | None
    created_at: str
    diff_from_previous_score: int | None = None


@dataclass
class ProjectEvolution:
    project_id: str
    project_name: str
    score_trend: str  # "rising" | "falling" | "stable" | "insufficient_data"
    score_volatility: float  # std dev of scores
    stage_progression: list[str]  # e.g. ["testnet", "mainnet"]
    stage_transitions: list[dict[str, str]] = field(default_factory=list)
    label_history: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    first_seen_at: str | None = None
    latest_snapshot_at: str | None = None
    snapshot_count: int = 0
    llm_context_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ProjectEvolutionService:
    """Service to reconstruct and analyze project evolution from project_history."""

    def __init__(self, conn: DbConnection | None = None) -> None:
        self._conn = conn

    def get_project_timeline(self, project_id: str, *, limit: int = 50) -> ProjectEvolution | None:
        """Get chronological timeline and evolution metrics for a project."""
        if self._conn is not None:
            return self._build_evolution(self._conn, project_id, limit=limit)

        with get_connection() as conn:
            return self._build_evolution(conn, project_id, limit=limit)

    def format_evolution_context(self, project_id: str) -> str:
        """Format a concise evolution summary for LLM context injection."""
        evolution = self.get_project_timeline(project_id)
        if not evolution:
            return ""
        return evolution.llm_context_summary

    def _build_evolution(self, conn: DbConnection, project_id: str, *, limit: int) -> ProjectEvolution | None:
        history_repo = ProjectHistoryRepository(conn)
        rows = history_repo.query_by_project(project_id, limit=limit)

        # Check if project exists
        proj_repo = ProjectRepository(conn)
        project_dict = proj_repo.get_by_id(project_id)
        if not project_dict and not rows:
            return None

        project_name = project_dict.get("name", project_id) if project_dict else project_id

        # If no history rows yet, synthesize a single baseline point from current project data
        if not rows and project_dict:
            created_at_str = str(project_dict.get("created_at") or "")
            point = TimelinePoint(
                snapshot_id=0,
                run_id="initial",
                score=project_dict.get("score"),
                label=project_dict.get("label"),
                stage=project_dict.get("stage"),
                weight_version=project_dict.get("weight_version"),
                created_at=created_at_str,
                diff_from_previous_score=0,
            )
            return ProjectEvolution(
                project_id=project_id,
                project_name=project_name,
                score_trend="insufficient_data",
                score_volatility=0.0,
                stage_progression=[str(project_dict.get("stage") or "unknown")],
                stage_transitions=[],
                label_history=[str(project_dict.get("label") or "UNKNOWN")],
                timeline=[asdict(point)],
                first_seen_at=created_at_str,
                latest_snapshot_at=created_at_str,
                snapshot_count=1,
                llm_context_summary=f"项目 {project_name} 仅有 1 次初始评估记录，阶段为 {project_dict.get('stage')}，分数为 {project_dict.get('score')}，当前标签为 {project_dict.get('label')}。",
            )

        # Sort chronological (oldest to newest)
        chrono_rows = sorted(rows, key=lambda r: (str(r.get("created_at") or ""), int(r.get("id") or 0)))

        timeline_points: list[TimelinePoint] = []
        prev_score: int | None = None
        scores_for_stats: list[int] = []

        stages_seen: list[str] = []
        labels_seen: list[str] = []
        transitions: list[dict[str, str]] = []

        prev_stage: str | None = None

        for r in chrono_rows:
            raw_score = r.get("score")
            score = int(raw_score) if raw_score is not None else None
            stage = str(r.get("stage") or "")
            label = str(r.get("label") or "")
            created_at = str(r.get("created_at") or "")

            diff = (score - prev_score) if (score is not None and prev_score is not None) else None
            if score is not None:
                prev_score = score
                scores_for_stats.append(score)

            if stage and stage not in stages_seen:
                stages_seen.append(stage)

            if label and (not labels_seen or labels_seen[-1] != label):
                labels_seen.append(label)

            if prev_stage and stage and prev_stage != stage:
                transitions.append(
                    {
                        "from_stage": prev_stage,
                        "to_stage": stage,
                        "timestamp": created_at,
                    }
                )
            if stage:
                prev_stage = stage

            timeline_points.append(
                TimelinePoint(
                    snapshot_id=int(r.get("id") or 0),
                    run_id=str(r.get("run_id") or ""),
                    score=score,
                    label=label,
                    stage=stage,
                    weight_version=r.get("weight_version"),
                    created_at=created_at,
                    diff_from_previous_score=diff,
                )
            )

        # Compute trend & volatility
        if len(scores_for_stats) >= 2:
            first_score = scores_for_stats[0]
            last_score = scores_for_stats[-1]
            delta = last_score - first_score
            if delta >= 5:
                trend = "rising"
            elif delta <= -5:
                trend = "falling"
            else:
                trend = "stable"

            mean_score = sum(scores_for_stats) / len(scores_for_stats)
            variance = sum((s - mean_score) ** 2 for s in scores_for_stats) / len(scores_for_stats)
            volatility = round(math.sqrt(variance), 2)
        else:
            trend = "insufficient_data" if len(scores_for_stats) < 1 else "stable"
            volatility = 0.0

        first_seen = timeline_points[0].created_at if timeline_points else None
        latest_seen = timeline_points[-1].created_at if timeline_points else None

        trend_zh_map = {
            "rising": "上升",
            "falling": "下行",
            "stable": "平稳",
            "insufficient_data": "数据样本不足",
        }
        trend_zh = trend_zh_map.get(trend, "平稳")
        current_score = scores_for_stats[-1] if scores_for_stats else "N/A"
        current_label = labels_seen[-1] if labels_seen else "N/A"
        stage_flow = " -> ".join(stages_seen) if stages_seen else "未知"

        llm_summary = (
            f"【项目演化画像】项目 {project_name} (ID: {project_id}) 首次记录于 {first_seen}。"
            f"历史累计 {len(timeline_points)} 次评估快照；阶段迁移轨迹：{stage_flow}；"
            f"评分走势呈{trend_zh}（当前分数: {current_score}，历史波动率: {volatility}）；"
            f"当前最新建议标签为 {current_label}。"
        )

        return ProjectEvolution(
            project_id=project_id,
            project_name=project_name,
            score_trend=trend,
            score_volatility=volatility,
            stage_progression=stages_seen,
            stage_transitions=transitions,
            label_history=labels_seen,
            timeline=[asdict(tp) for tp in timeline_points],
            first_seen_at=first_seen,
            latest_snapshot_at=latest_seen,
            snapshot_count=len(timeline_points),
            llm_context_summary=llm_summary,
        )
