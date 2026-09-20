"""Anomaly Detection and Data Quality Alert router (W12-04).

Endpoints:
- GET /api/v1/anomalies: 获取评分漂移与数据质量巡检报告（支持 force_refresh=true 强制重新扫描）
"""
from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.services.anomaly_detection import AnomalyDetectionService

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["anomalies"])


class AnomalyReportResponse(BaseModel):
    """异常检测与质量告警报告响应."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "data": {
                    "overall_status": "healthy",
                    "checked_at": "2026-09-19T10:00:00Z",
                    "total_anomalies": 0,
                    "critical_count": 0,
                    "warning_count": 0,
                    "info_count": 0,
                    "drift_summary": {
                        "total_projects": 50,
                        "mean_score": 52.4,
                        "median_score": 53.0,
                        "stddev_score": 14.2,
                        "zero_score_count": 1,
                        "zero_score_ratio": 0.02,
                        "label_counts": {"FARM": 12, "WATCH": 28, "IGNORE": 10},
                        "label_ratios": {"FARM": 0.24, "WATCH": 0.56, "IGNORE": 0.20},
                        "baseline_mean": 50.0,
                        "mean_drift": 2.4,
                        "out_of_bounds_count": 0,
                    },
                    "quality_summary": {
                        "p0_completeness": 1.0,
                        "p1_completeness": 0.94,
                        "p0_missing_count": 0,
                        "p1_missing_count": 3,
                        "quarantine_pending": 0,
                        "stale_sources": [],
                        "total_sources_monitored": 5,
                    },
                    "anomalies": [],
                },
            }
        }
    )

    ok: bool = True
    data: dict[str, Any] = Field(..., description="异常巡检与漂移评估报告")


@router.get(
    "/anomalies",
    response_model=AnomalyReportResponse,
    summary="获取评分漂移与数据质量巡检报告",
    description="主动扫描全仓评分分布（漂移/极化/0分）与数据质量指标（P0/P1完整性、时效性、隔离积压）（W12-04）。",
)
def get_anomalies(
    force_refresh: bool = Query(False, description="是否跳过内存缓存并强制重新全量巡检"),
) -> AnomalyReportResponse:
    """获取系统评分漂移与数据质量检测报告（只读诊断，支持匿名 token）."""
    try:
        svc = AnomalyDetectionService()
        report = svc.run_all_checks(force_refresh=force_refresh)
        return AnomalyReportResponse(ok=True, data=report.to_dict())
    except Exception as e:
        logger.error("api.anomalies.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to run anomaly detection checks"},
        ) from e
