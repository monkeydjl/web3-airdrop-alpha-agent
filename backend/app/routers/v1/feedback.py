"""Feedback & Events Endpoints.

User feedback and implicit event tracking for the V2 feedback loop.

Reference:
- API_SPEC.md §反馈相关端点
- ENGINEERING_ROADMAP.md §24 反馈校准
- docs/DATA_QUALITY.md
"""

from datetime import UTC, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.db import get_connection, insert_returning_id

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["feedback"])


# ═══════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════


class FeedbackRequest(BaseModel):
    """用户反馈请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": "layerx-001",
                "signal": "useful",
                "note": "Good airdrop candidate",
                "outcome": "airdropped",
            }
        }
    )

    # 长度上限见 SECURITY.md §5.1：此前四个字段全部无界，实测 20MB 的 note
    # 会原样落库，未鉴权即可重复调用 → 磁盘耗尽。取值域用 Literal 收紧，
    # WEIGHT_CALIBRATION §3.1 本就规定了这两个枚举。
    project_id: str = Field(..., min_length=1, max_length=64, description="项目 ID")
    user_id: str | None = Field(None, max_length=64, description="用户匿名标识（可选）")
    signal: Literal["useful", "useless", "wrong_label", "correct_outcome"] = Field(..., description="反馈信号")
    note: str | None = Field(None, max_length=2000, description="用户备注")
    outcome: Literal["airdropped", "not_airdropped", "pumped", "dumped"] | None = Field(None, description="实际结果")


class EventRequest(BaseModel):
    """隐式事件埋点请求。"""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "project_id": "layerx-001",
                "event_type": "expand",
                "detail": '{"duration_ms": 1200}',
            }
        }
    )

    # 长度上限与 FeedbackRequest 同理（SECURITY.md §5.1）：/events 同为未鉴权
    # 可写端点，detail 设计上存 JSON 字符串本就无界，缺上限则一次未鉴权重复
    # 调用即可写入任意大 payload → 磁盘耗尽。detail 略宽于 note 因需容纳 JSON。
    project_id: str | None = Field(None, max_length=64, description="项目 ID（全局事件可为空）")
    user_id: str | None = Field(None, max_length=64, description="用户匿名标识（可选）")
    event_type: str = Field(..., min_length=1, max_length=32, description="事件类型: click|expand|feedback|view")
    detail: str | None = Field(None, max_length=4000, description="事件详情 JSON 字符串")


class FeedbackResponse(BaseModel):
    """反馈/事件响应。"""

    ok: bool = True
    data: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """错误响应。"""

    ok: bool = False
    error: dict[str, str]


# ═══════════════════════════════════════════════════════════════
# Endpoints
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/feedback",
    response_model=FeedbackResponse,
    responses={
        400: {"model": ErrorResponse, "description": "输入验证失败或反馈系统未启用"},
        500: {"model": ErrorResponse, "description": "数据库错误"},
    },
    summary="提交用户反馈",
    description="用户对项目评分结果提交反馈，用于后续权重校准。",
)
def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """提交用户反馈。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    try:
        with get_connection() as conn:
            feedback_id = insert_returning_id(
                conn,
                """
                INSERT INTO feedback (project_id, user_id, signal, note, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request.project_id, request.user_id, request.signal, request.note, request.outcome),
            )
            conn.commit()

        logger.info(
            "feedback.submitted",
            project_id=request.project_id,
            signal=request.signal,
            feedback_id=feedback_id,
        )

        return FeedbackResponse(
            data={
                "feedback_id": feedback_id,
                "project_id": request.project_id,
                "signal": request.signal,
            }
        )
    except Exception as e:
        logger.error("feedback.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to save feedback"},
        ) from e


@router.get(
    "/feedback/{project_id}",
    response_model=FeedbackResponse,
    summary="查询项目反馈",
    description="获取指定项目的所有用户反馈统计。",
)
def get_feedback(project_id: str) -> FeedbackResponse:
    """查询项目反馈。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM feedback WHERE project_id = ? ORDER BY created_at DESC",
                (project_id,),
            ).fetchall()

            feedback_list = [dict(row) for row in rows]

            # Aggregate signal counts
            counts: dict[str, int] = {}
            for row in rows:
                signal = row["signal"]
                counts[signal] = counts.get(signal, 0) + 1

        return FeedbackResponse(
            data={
                "project_id": project_id,
                "count": len(feedback_list),
                "signals": counts,
                "items": feedback_list,
            }
        )
    except Exception as e:
        logger.error("feedback.query_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to query feedback"},
        ) from e


@router.post(
    "/events",
    response_model=FeedbackResponse,
    responses={
        400: {"model": ErrorResponse, "description": "事件系统未启用"},
        500: {"model": ErrorResponse, "description": "数据库错误"},
    },
    summary="提交隐式事件",
    description="埋点用户隐式行为事件（如点击、展开）。",
)
def submit_event(request: EventRequest) -> FeedbackResponse:
    """提交隐式事件埋点。"""
    if not settings.enable_events_tracking:
        raise HTTPException(
            status_code=400,
            detail={"code": "EVENTS_DISABLED", "message": "Events tracking is disabled"},
        )

    try:
        with get_connection() as conn:
            event_id = insert_returning_id(
                conn,
                """
                INSERT INTO events (project_id, user_id, event_type, detail, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    request.project_id,
                    request.user_id,
                    request.event_type,
                    request.detail,
                    datetime.now(UTC),
                ),
            )
            conn.commit()

        logger.info(
            "event.submitted",
            project_id=request.project_id,
            event_type=request.event_type,
            event_id=event_id,
        )

        return FeedbackResponse(
            data={
                "event_id": event_id,
                "event_type": request.event_type,
            }
        )
    except Exception as e:
        logger.error("event.failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to save event"},
        ) from e


# ═══════════════════════════════════════════════════════════════
# Calibration Status Endpoint
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/calibration/status",
    response_model=FeedbackResponse,
    summary="校准状态",
    description=(
        "返回权重校准的当前状态：权重版本、反馈样本数与门禁阈值、"
        "信号分布、以及最近的 weight_changelog 记录。"
        "\n\nReference: WEIGHT_CALIBRATION.md §3.3 / §7"
    ),
)
def get_calibration_status() -> FeedbackResponse:
    """获取权重校准状态。"""
    min_samples = 200  # WEIGHT_CALIBRATION.md §3.3

    try:
        with get_connection() as conn:
            # 反馈总数
            total_row = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()
            total_feedback = int(total_row[0]) if total_row else 0

            # 强监督样本数（wrong_label + outcome 非空）
            strong_row = conn.execute(
                "SELECT COUNT(*) FROM feedback WHERE signal = 'wrong_label' OR outcome IS NOT NULL"
            ).fetchone()
            strong_samples = int(strong_row[0]) if strong_row else 0

            # 信号分布
            signal_rows = conn.execute(
                "SELECT signal, COUNT(*) as cnt FROM feedback GROUP BY signal"
            ).fetchall()
            signal_counts = {row["signal"]: row["cnt"] for row in signal_rows}

            # outcome 分布
            outcome_rows = conn.execute(
                "SELECT outcome, COUNT(*) as cnt FROM feedback WHERE outcome IS NOT NULL GROUP BY outcome"
            ).fetchall()
            outcome_counts = {row["outcome"]: row["cnt"] for row in outcome_rows}

            # 最近 weight_changelog 记录
            changelog_rows = conn.execute(
                """
                SELECT from_version, to_version, weights_json, sample_size,
                       metrics_json, triggered_by, status, created_at
                FROM weight_changelog
                ORDER BY created_at DESC
                LIMIT 5
                """
            ).fetchall()

            import json as _json

            changelog = []
            for row in changelog_rows:
                metrics = {}
                try:
                    metrics = _json.loads(row["metrics_json"]) if row["metrics_json"] else {}
                except (ValueError, TypeError):
                    pass
                changelog.append(
                    {
                        "from_version": row["from_version"],
                        "to_version": row["to_version"],
                        "sample_size": row["sample_size"],
                        "metrics": metrics,
                        "triggered_by": row["triggered_by"],
                        "status": row["status"],
                        "created_at": str(row["created_at"]) if row["created_at"] else None,
                    }
                )

        # 当前权重版本
        from app.config import settings

        ready = total_feedback >= min_samples

        return FeedbackResponse(
            data={
                "weight_version": settings.weight_version,
                "min_samples_gate": min_samples,
                "total_feedback": total_feedback,
                "strong_samples": strong_samples,
                "calibration_ready": ready,
                "samples_needed": max(0, min_samples - total_feedback),
                "signal_counts": signal_counts,
                "outcome_counts": outcome_counts,
                "changelog": changelog,
            }
        )
    except Exception as e:
        logger.error("calibration.status_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to get calibration status"},
        ) from e
