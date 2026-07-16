"""Feedback & Events Endpoints.

User feedback and implicit event tracking for the V2 feedback loop.

Reference:
- API_SPEC.md §反馈相关端点
- ENGINEERING_ROADMAP.md §24 反馈校准
- docs/DATA_QUALITY.md
"""

from datetime import datetime

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.db import get_connection

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

    project_id: str = Field(..., description="项目 ID")
    user_id: str | None = Field(None, description="用户匿名标识（可选）")
    signal: str = Field(..., description="反馈信号: useful|useless|wrong_label|correct_outcome")
    note: str | None = Field(None, description="用户备注")
    outcome: str | None = Field(None, description="实际结果: airdropped|not_airdropped|pumped|dumped")


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

    project_id: str | None = Field(None, description="项目 ID（全局事件可为空）")
    user_id: str | None = Field(None, description="用户匿名标识（可选）")
    event_type: str = Field(..., description="事件类型: click|expand|feedback|view")
    detail: str | None = Field(None, description="事件详情 JSON 字符串")


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
async def submit_feedback(request: FeedbackRequest) -> FeedbackResponse:
    """提交用户反馈。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO feedback (project_id, user_id, signal, note, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request.project_id, request.user_id, request.signal, request.note, request.outcome),
            )
            conn.commit()
            feedback_id = cursor.lastrowid

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
        logger.error("feedback.failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": f"Failed to save feedback: {e!s}"},
        ) from e


@router.get(
    "/feedback/{project_id}",
    response_model=FeedbackResponse,
    summary="查询项目反馈",
    description="获取指定项目的所有用户反馈统计。",
)
async def get_feedback(project_id: str) -> FeedbackResponse:
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
        logger.error("feedback.query_failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": f"Failed to query feedback: {e!s}"},
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
async def submit_event(request: EventRequest) -> FeedbackResponse:
    """提交隐式事件埋点。"""
    if not settings.enable_events_tracking:
        raise HTTPException(
            status_code=400,
            detail={"code": "EVENTS_DISABLED", "message": "Events tracking is disabled"},
        )

    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO events (project_id, user_id, event_type, detail, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    request.project_id,
                    request.user_id,
                    request.event_type,
                    request.detail,
                    datetime.now(),
                ),
            )
            conn.commit()
            event_id = cursor.lastrowid

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
        logger.error("event.failed", error=str(e))
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": f"Failed to save event: {e!s}"},
        ) from e
