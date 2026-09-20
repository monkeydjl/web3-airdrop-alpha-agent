"""Anomaly Detection and Data Quality Alerting Service (W12-04).

Implements automated drift and data quality detection:
- Score distribution drift (mean/median shift, label distribution skew, zero score spike)
- Data quality degradation (P0/P1 completeness violations, source freshness, quarantine backlog)
- Health status aggregation and structured logging

References:
- ENGINEERING_ROADMAP.md §12 / §22
- TASK_BREAKDOWN.md W12-04
- DATA_QUALITY.md §2, §3, §4, §5.2
- OBSERVABILITY.md §3.2
"""

from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

import structlog

from app.db import DbConnection, get_connection
from app.quarantine import quarantine_count

logger = structlog.get_logger(__name__)

AnomalySeverity = Literal["info", "warning", "critical"]


@dataclass
class AnomalyItem:
    id: str
    type: str
    severity: AnomalySeverity
    title: str
    description: str
    metric_name: str
    metric_value: float | int | str
    threshold: float | int | str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScoreDriftSummary:
    total_projects: int = 0
    mean_score: float = 0.0
    median_score: float = 0.0
    stddev_score: float = 0.0
    zero_score_count: int = 0
    zero_score_ratio: float = 0.0
    label_counts: dict[str, int] = field(default_factory=dict)
    label_ratios: dict[str, float] = field(default_factory=dict)
    baseline_mean: float = 50.0
    mean_drift: float = 0.0
    out_of_bounds_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DataQualitySummary:
    p0_completeness: float = 1.0
    p1_completeness: float = 1.0
    p0_missing_count: int = 0
    p1_missing_count: int = 0
    quarantine_pending: int = 0
    stale_sources: list[str] = field(default_factory=list)
    total_sources_monitored: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AnomalyReport:
    overall_status: Literal["healthy", "warning", "critical"]
    checked_at: str
    total_anomalies: int
    critical_count: int
    warning_count: int
    info_count: int
    drift_summary: ScoreDriftSummary
    quality_summary: DataQualitySummary
    anomalies: list[AnomalyItem]

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall_status": self.overall_status,
            "checked_at": self.checked_at,
            "total_anomalies": self.total_anomalies,
            "critical_count": self.critical_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "drift_summary": self.drift_summary.to_dict(),
            "quality_summary": self.quality_summary.to_dict(),
            "anomalies": [a.to_dict() for a in self.anomalies],
        }


class AnomalyDetectionService:
    """Service for detecting scoring drift and data quality anomalies."""

    _cached_report: AnomalyReport | None = None
    _cached_at: float = 0.0
    _cache_ttl_seconds: float = 60.0

    def __init__(self, conn: DbConnection | None = None):
        self._conn = conn

    def _get_conn(self) -> DbConnection:
        return self._conn if self._conn is not None else get_connection()

    def _should_close(self) -> bool:
        return self._conn is None

    def detect_score_drift(self) -> tuple[ScoreDriftSummary, list[AnomalyItem]]:
        """Analyze score distribution and detect drift anomalies."""
        conn = self._get_conn()
        anomalies: list[AnomalyItem] = []
        try:
            cur = conn.execute(
                "SELECT id, score, label FROM projects"
            )
            rows = [dict(r) for r in cur.fetchall()]
        finally:
            if self._should_close():
                conn.close()

        total = len(rows)
        if total == 0:
            summary = ScoreDriftSummary(
                total_projects=0,
                mean_score=0.0,
                median_score=0.0,
                stddev_score=0.0,
                zero_score_count=0,
                zero_score_ratio=0.0,
                label_counts={},
                label_ratios={},
                baseline_mean=50.0,
                mean_drift=0.0,
                out_of_bounds_count=0,
            )
            return summary, anomalies

        scores: list[float] = []
        label_counts: dict[str, int] = {"FARM": 0, "WATCH": 0, "IGNORE": 0}
        zero_score_count = 0
        out_of_bounds_count = 0

        for r in rows:
            s_val = r.get("score")
            score = float(s_val) if s_val is not None else 0.0
            scores.append(score)

            if score <= 0:
                zero_score_count += 1
            if score < 0 or score > 100:
                out_of_bounds_count += 1

            lbl = str(r.get("label") or "IGNORE").upper()
            label_counts[lbl] = label_counts.get(lbl, 0) + 1

        mean_score = sum(scores) / total
        sorted_scores = sorted(scores)
        if total % 2 == 1:
            median_score = sorted_scores[total // 2]
        else:
            median_score = (sorted_scores[total // 2 - 1] + sorted_scores[total // 2]) / 2.0

        variance = sum((s - mean_score) ** 2 for s in scores) / total
        stddev_score = math.sqrt(variance)
        zero_score_ratio = zero_score_count / total

        label_ratios = {k: round(v / total, 4) for k, v in label_counts.items()}

        baseline_mean = 50.0
        mean_drift = round(mean_score - baseline_mean, 2)

        summary = ScoreDriftSummary(
            total_projects=total,
            mean_score=round(mean_score, 2),
            median_score=round(median_score, 2),
            stddev_score=round(stddev_score, 2),
            zero_score_count=zero_score_count,
            zero_score_ratio=round(zero_score_ratio, 4),
            label_counts=label_counts,
            label_ratios=label_ratios,
            baseline_mean=baseline_mean,
            mean_drift=mean_drift,
            out_of_bounds_count=out_of_bounds_count,
        )

        # 1. 均值偏离基线 > 15.0 pts
        if abs(mean_drift) > 15.0:
            anomalies.append(
                AnomalyItem(
                    id="score_mean_drift",
                    type="score_drift",
                    severity="warning",
                    title="评分均值显著偏离基线",
                    description=(
                        f"全仓评分均值 ({mean_score:.1f}) 与基准值 ({baseline_mean:.1f}) "
                        f"偏离 {abs(mean_drift):.1f} 分，超出 ±15.0 容忍阈值。"
                    ),
                    metric_name="airdrop_score_mean_drift",
                    metric_value=mean_drift,
                    threshold=15.0,
                    details={"mean_score": round(mean_score, 2), "baseline_mean": baseline_mean},
                )
            )

        # 2. 标签分布偏斜（仅在样本 >= 10 时检验，防小样本误报）
        if total >= 10:
            farm_ratio = label_ratios.get("FARM", 0.0)
            if farm_ratio > 0.40:
                anomalies.append(
                    AnomalyItem(
                        id="label_skew_farm_high",
                        type="score_drift",
                        severity="warning",
                        title="FARM 标签比例过高",
                        description=(
                            f"当前 FARM 标签占比达 {farm_ratio * 100:.1f}% (>40%)，"
                            "可能存在资格门宽松放行或评分阈值过低风险。"
                        ),
                        metric_name="airdrop_farm_ratio",
                        metric_value=farm_ratio,
                        threshold=0.40,
                        details={"farm_count": label_counts.get("FARM", 0), "total": total},
                    )
                )
            elif farm_ratio == 0.0:
                anomalies.append(
                    AnomalyItem(
                        id="label_skew_farm_zero",
                        type="score_drift",
                        severity="warning",
                        title="全仓无 FARM 重点参与项目",
                        description="当前项目全量评分为 0% FARM，可能存在过度否决或关键空投信号缺失。",
                        metric_name="airdrop_farm_ratio",
                        metric_value=0.0,
                        threshold=0.01,
                        details={"total": total},
                    )
                )

            # 3. 0 分项目集中爆发
            if zero_score_ratio > 0.30:
                anomalies.append(
                    AnomalyItem(
                        id="score_zero_spike",
                        type="score_drift",
                        severity="critical",
                        title="0 分项目爆发式增多",
                        description=(
                            f"当前有 {zero_score_count} 个项目（{zero_score_ratio * 100:.1f}%）"
                            "评分为 0，超出 30% 告警阈值，可能存在评分决策引擎未启动或数据大面积损坏。"
                        ),
                        metric_name="airdrop_zero_score_ratio",
                        metric_value=zero_score_ratio,
                        threshold=0.30,
                        details={"zero_count": zero_score_count, "total": total},
                    )
                )

        # 4. 越界评分 (score < 0 or > 100)
        if out_of_bounds_count > 0:
            anomalies.append(
                AnomalyItem(
                    id="score_out_of_bounds",
                    type="score_drift",
                    severity="critical",
                    title="存在超出 [0, 100] 合法范围的评分",
                    description=f"发现 {out_of_bounds_count} 个项目的评分超出 [0, 100] 合法区间。",
                    metric_name="airdrop_out_of_bounds_count",
                    metric_value=out_of_bounds_count,
                    threshold=0,
                    details={"out_of_bounds_count": out_of_bounds_count},
                )
            )

        return summary, anomalies

    def detect_data_quality_issues(self) -> tuple[DataQualitySummary, list[AnomalyItem]]:
        """Inspect database for data quality degradation (P0/P1 completeness, freshness, quarantine)."""
        conn = self._get_conn()
        anomalies: list[AnomalyItem] = []
        try:
            # P0 检查：name, sector, score, label (DATA_QUALITY.md §3.1 要求 100% 完整)
            cur = conn.execute(
                """
                SELECT
                    COUNT(*) as total_projects,
                    SUM(CASE WHEN name IS NULL OR name = '' THEN 1 ELSE 0 END) as missing_name,
                    SUM(CASE WHEN sector IS NULL OR sector = '' THEN 1 ELSE 0 END) as missing_sector,
                    SUM(CASE WHEN score IS NULL THEN 1 ELSE 0 END) as missing_score,
                    SUM(CASE WHEN label IS NULL OR label NOT IN ('FARM', 'WATCH', 'IGNORE') THEN 1 ELSE 0 END) as invalid_label,
                    SUM(CASE WHEN raw_signals IS NULL OR raw_signals = '' OR raw_signals = '{}' THEN 1 ELSE 0 END) as missing_signals,
                    SUM(CASE WHEN narrative_json IS NULL OR narrative_json = '' THEN 1 ELSE 0 END) as missing_narrative
                FROM projects
                """
            )
            row = cur.fetchone()
            p_data = dict(row) if row else {}
        finally:
            if self._should_close():
                conn.close()

        total = int(p_data.get("total_projects") or 0)
        p0_missing_name = int(p_data.get("missing_name") or 0)
        p0_missing_sector = int(p_data.get("missing_sector") or 0)
        p0_missing_score = int(p_data.get("missing_score") or 0)
        p0_invalid_label = int(p_data.get("invalid_label") or 0)
        p0_missing_total = p0_missing_name + p0_missing_sector + p0_missing_score + p0_invalid_label

        p1_missing_signals = int(p_data.get("missing_signals") or 0)
        p1_missing_narrative = int(p_data.get("missing_narrative") or 0)
        p1_missing_total = p1_missing_signals + p1_missing_narrative

        if total > 0:
            p0_completeness = max(0.0, 1.0 - (p0_missing_total / (total * 4.0)))
            p1_completeness = max(0.0, 1.0 - (p1_missing_total / (total * 2.0)))
        else:
            p0_completeness = 1.0
            p1_completeness = 1.0

        # P0 违背判定（要求 100%）
        if p0_missing_total > 0 and total > 0:
            anomalies.append(
                AnomalyItem(
                    id="p0_completeness_violation",
                    type="data_quality",
                    severity="critical",
                    title="P0 核心字段完整性缺失",
                    description=(
                        f"P0 核心字段（name/sector/score/label）出现 {p0_missing_total} 处缺失或非法值，"
                        f"完整性为 {p0_completeness * 100:.1f}%，低于 100% 硬性指标。"
                    ),
                    metric_name="airdrop_data_completeness_p0",
                    metric_value=round(p0_completeness, 4),
                    threshold=1.0,
                    details={
                        "missing_name": p0_missing_name,
                        "missing_sector": p0_missing_sector,
                        "missing_score": p0_missing_score,
                        "invalid_label": p0_invalid_label,
                    },
                )
            )

        # P1 降低判定（要求 >= 80%）
        if p1_completeness < 0.80 and total >= 5:
            anomalies.append(
                AnomalyItem(
                    id="p1_completeness_degraded",
                    type="data_quality",
                    severity="warning",
                    title="P1 关键字段完整性下降",
                    description=(
                        f"P1 关键字段（raw_signals/narrative_json）完整性为 {p1_completeness * 100:.1f}%，"
                        "低于 80% 目标阈值。"
                    ),
                    metric_name="airdrop_data_completeness_p1",
                    metric_value=round(p1_completeness, 4),
                    threshold=0.80,
                    details={
                        "missing_signals": p1_missing_signals,
                        "missing_narrative": p1_missing_narrative,
                    },
                )
            )

        # Quarantine 积压检查
        q_pending = quarantine_count()
        if q_pending > 50:
            anomalies.append(
                AnomalyItem(
                    id="quarantine_backlog",
                    type="data_quality",
                    severity="warning",
                    title="隔离区脏数据积压超限",
                    description=f"当前隔离区积压了 {q_pending} 条未处理脏数据，超出 50 条阈值。",
                    metric_name="airdrop_quarantine_pending",
                    metric_value=q_pending,
                    threshold=50,
                    details={"pending_count": q_pending},
                )
            )

        # 采集源时效性检查（最近一次 sync 距今 > 72h）
        stale_sources: list[str] = []
        total_sources_monitored = 0
        conn2 = self._get_conn()
        try:
            cur = conn2.execute(
                """
                SELECT source_id, MAX(started_at) as last_sync
                FROM collection_logs
                WHERE status = 'success'
                GROUP BY source_id
                """
            )
            c_rows = [dict(r) for r in cur.fetchall()]
        except Exception:
            c_rows = []
        finally:
            if self._should_close():
                conn2.close()

        total_sources_monitored = len(c_rows)
        now_dt = datetime.now(UTC)
        for cr in c_rows:
            sid = cr.get("source_id")
            last_sync_str = cr.get("last_sync")
            if not sid or not last_sync_str:
                continue
            try:
                # SQLite timestamp may lack timezone; treat as UTC
                if "T" in str(last_sync_str):
                    dt = datetime.fromisoformat(str(last_sync_str).replace("Z", "+00:00"))
                else:
                    dt = datetime.strptime(str(last_sync_str), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
                age_hours = (now_dt - dt).total_seconds() / 3600.0
                if age_hours > 72.0:
                    stale_sources.append(sid)
                    anomalies.append(
                        AnomalyItem(
                            id=f"stale_source_{sid}",
                            type="data_quality",
                            severity="warning",
                            title=f"采集源 {sid} 时效性超时",
                            description=(
                                f"数据源 {sid} 最近一次成功同步距今已 {age_hours:.1f} 小时，"
                                "超过 72 小时 (3×TTL) 阈值。"
                            ),
                            metric_name="airdrop_data_freshness_seconds",
                            metric_value=round(age_hours * 3600.0, 1),
                            threshold=72.0 * 3600.0,
                            details={"source_id": sid, "age_hours": round(age_hours, 1)},
                        )
                    )
            except Exception as exc:
                logger.debug("quality.scan.stale_parse_failed", source_id=sid, error=str(exc))
                continue

        summary = DataQualitySummary(
            p0_completeness=round(p0_completeness, 4),
            p1_completeness=round(p1_completeness, 4),
            p0_missing_count=p0_missing_total,
            p1_missing_count=p1_missing_total,
            quarantine_pending=q_pending,
            stale_sources=stale_sources,
            total_sources_monitored=total_sources_monitored,
        )

        return summary, anomalies

    def run_all_checks(self, force_refresh: bool = False) -> AnomalyReport:
        """Run all anomaly detection checks and aggregate health report."""
        now = time.time()
        if (
            not force_refresh
            and AnomalyDetectionService._cached_report is not None
            and (now - AnomalyDetectionService._cached_at) < AnomalyDetectionService._cache_ttl_seconds
        ):
            return AnomalyDetectionService._cached_report

        drift_summary, drift_anomalies = self.detect_score_drift()
        quality_summary, quality_anomalies = self.detect_data_quality_issues()

        all_anomalies = drift_anomalies + quality_anomalies

        critical_count = sum(1 for a in all_anomalies if a.severity == "critical")
        warning_count = sum(1 for a in all_anomalies if a.severity == "warning")
        info_count = sum(1 for a in all_anomalies if a.severity == "info")

        if critical_count > 0:
            overall_status: Literal["healthy", "warning", "critical"] = "critical"
        elif warning_count > 0:
            overall_status = "warning"
        else:
            overall_status = "healthy"

        report = AnomalyReport(
            overall_status=overall_status,
            checked_at=datetime.now(UTC).isoformat(),
            total_anomalies=len(all_anomalies),
            critical_count=critical_count,
            warning_count=warning_count,
            info_count=info_count,
            drift_summary=drift_summary,
            quality_summary=quality_summary,
            anomalies=all_anomalies,
        )

        # 结构化日志留痕 (OBSERVABILITY §2.2)
        if drift_anomalies:
            logger.warning(
                "quality.scan.drift_detected",
                drift_count=len(drift_anomalies),
                mean_score=drift_summary.mean_score,
                mean_drift=drift_summary.mean_drift,
            )
        if quality_anomalies:
            logger.warning(
                "quality.scan.degradation_detected",
                quality_count=len(quality_anomalies),
                p0_completeness=quality_summary.p0_completeness,
            )
        if not all_anomalies:
            logger.info("quality.scan.completed", status="healthy")

        AnomalyDetectionService._cached_report = report
        AnomalyDetectionService._cached_at = now
        return report
