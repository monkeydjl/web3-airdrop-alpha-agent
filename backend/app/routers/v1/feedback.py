"""Feedback & Events Endpoints.

User feedback and implicit event tracking for the V2 feedback loop.

Reference:
- API_SPEC.md §反馈相关端点
- ENGINEERING_ROADMAP.md §24 反馈校准
- docs/DATA_QUALITY.md
"""

import contextlib
from datetime import UTC, datetime
from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from app.auth import ROLE_ADMIN, get_current_user
from app.config import settings
from app.db import get_connection, insert_returning_id
from app.metrics import record_feedback
from app.services.user_scope import DEFAULT_USER, build_user_scope_filter, owned_project_ids, owned_project_ids_where

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


class FeedbackBatchItem(BaseModel):
    """批量反馈中的单条结果标记。"""

    project_id: str = Field(..., min_length=1, max_length=64, description="项目 ID")
    signal: Literal["useful", "useless", "wrong_label", "correct_outcome"] = Field(
        "correct_outcome", description="反馈信号（批量标记默认按实际结果记录）"
    )
    outcome: Literal["airdropped", "not_airdropped", "pumped", "dumped"] | None = Field(None, description="实际结果")
    note: str | None = Field(None, max_length=2000, description="用户备注")


class FeedbackBatchRequest(BaseModel):
    """批量提交结果标记。

    校准门禁要求 200 条样本（WEIGHT_CALIBRATION §3.3），而逐条进入项目详情页
    提交的成本让这个数字实际上不可能达到 —— 实测线上 feedback 表为 0 条，
    权重校准能力因此永久空转。批量端点把「标十几个项目」压缩到一次请求。

    条数上限刻意设为 50 而非门禁的 200：本端点与 POST /feedback 一样只需匿名
    token（PUBLIC/ADMIN 前缀都不含 /api/v1/feedback），若允许单请求 200 条，
    一次调用就能把校准门禁**一次性填满**（已实测：注入 200 条伪造 project_id
    后 calibration_ready 立刻变 True）。压到 50 条使填满门禁至少需要 4 次请求，
    与限流叠加后提高投毒成本；真实使用场景一屏也标不到 50 个。
    """

    items: list[FeedbackBatchItem] = Field(..., min_length=1, max_length=50, description="结果标记列表")
    user_id: str | None = Field(None, max_length=64, description="用户匿名标识（可选）")


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
    data: dict[str, Any] = Field(default_factory=dict)


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
def submit_feedback(request: FeedbackRequest, req: Request) -> FeedbackResponse:
    """提交用户反馈。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = request.user_id or current_user["user_id"]
    elif current_user["user_id"] != "anonymous":
        uid = current_user["user_id"]
    else:
        uid = request.user_id or "anonymous"

    try:
        with get_connection() as conn:
            feedback_id = insert_returning_id(
                conn,
                """
                INSERT INTO feedback (project_id, user_id, signal, note, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (request.project_id, uid, request.signal, request.note, request.outcome),
            )
            conn.commit()

        record_feedback(signal=request.signal)

        logger.info(
            "feedback.submitted",
            project_id=request.project_id,
            signal=request.signal,
            feedback_id=feedback_id,
            user_id=uid,
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


@router.post(
    "/feedback/batch",
    response_model=FeedbackResponse,
    responses={
        400: {"model": ErrorResponse, "description": "输入验证失败或反馈系统未启用"},
        500: {"model": ErrorResponse, "description": "数据库错误"},
    },
    summary="批量提交结果标记",
    description=(
        "一次提交多个项目的实际结果，用于快速积累权重校准样本。\n\n"
        "校准门禁需要 200 条样本，逐条提交成本过高会让校准永久无法启动。"
        "\n\nReference: WEIGHT_CALIBRATION.md §3.3"
    ),
)
def submit_feedback_batch(request: FeedbackBatchRequest, req: Request) -> FeedbackResponse:
    """批量写入结果标记。整批在同一事务内提交，避免部分写入。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = request.user_id or current_user["user_id"]
    elif current_user["user_id"] != "anonymous":
        uid = current_user["user_id"]
    else:
        uid = request.user_id or "anonymous"

    project_ids = [item.project_id for item in request.items]

    try:
        with get_connection() as conn:
            # 先校验项目存在，再写入。
            placeholders = ",".join("?" for _ in set(project_ids))
            rows = conn.execute(
                f"SELECT id FROM projects WHERE id IN ({placeholders})",  # noqa: S608 — 占位符按数量生成，取值全部绑定
                tuple(set(project_ids)),
            ).fetchall()
            known = {str(r[0]) for r in rows}
            unknown = sorted(set(project_ids) - known)
            if unknown:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "NOT_FOUND",
                        "message": f"Unknown project_id(s): {', '.join(unknown[:5])}"
                        + (f" (+{len(unknown) - 5} more)" if len(unknown) > 5 else ""),
                    },
                )

            # 单事务批量插入：任一条失败整批回滚，避免"标了 10 个成功 3 个"
            # 这种用户无法分辨的中间状态。
            conn.executemany(
                """
                INSERT INTO feedback (project_id, user_id, signal, note, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                [(item.project_id, uid, item.signal, item.note, item.outcome) for item in request.items],
            )
            conn.commit()

        for item in request.items:
            record_feedback(signal=item.signal)

        logger.info(
            "feedback.batch_submitted",
            count=len(request.items),
            project_count=len(set(project_ids)),
            user_id=uid,
        )

        return FeedbackResponse(
            data={
                "saved": len(request.items),
                "project_ids": project_ids,
            }
        )
    except HTTPException:
        # 上面的 404（未知 project_id）是预期的业务响应，不能被下面的兜底
        # 改写成 500 —— 否则调用方看到「服务器错误」而不是「项目不存在」。
        raise
    except Exception as e:
        logger.error("feedback.batch_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to save feedback batch"},
        ) from e


# ⚠ 顺序敏感：本路由必须声明在 /feedback/{project_id} **之前**。
# FastAPI 按声明顺序匹配，动态路由在前会把 "pending-review" 当作 project_id
# 落进 get_feedback，返回 {"project_id":"pending-review","count":0,"items":[]}
# —— HTTP 200 但内容全空，属于最难察觉的一类 bug（本次已实测踩到并修正）。
@router.get(
    "/feedback/pending-review",
    response_model=FeedbackResponse,
    responses={500: {"model": ErrorResponse, "description": "数据库错误"}},
    summary="待标记结果的项目",
    description=(
        "列出「值得标结果但还没标过」的项目，供快速标记页逐条打勾。\n\n"
        "排序：有交互记录但未标结果的排最前（你真投入过，结果最可信），"
        "其次是 FARM/WATCH 高分项目。已标过结果的项目不再出现。"
    ),
)
def get_pending_review(
    req: Request,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    user_id: str | None = Query(None, max_length=64, description="用户标识（仅管理员可指定，缺省 default）"),
) -> FeedbackResponse:
    """返回待标记结果的项目列表。"""
    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = user_id or DEFAULT_USER
    else:
        uid = current_user["user_id"] if current_user["user_id"] != "anonymous" else (user_id or DEFAULT_USER)

    try:
        with get_connection() as conn:
            # 已有 outcome 的项目不再需要标记。
            # 走统一的归属过滤（user_scope）：此前这里完全没有用户过滤，
            # 与 /action-queue 的口径不一致 —— 多用户启用后会把别人标过的项目
            # 从你的待标清单里剔掉，也会把别人的交互记录当成你的。
            done = owned_project_ids_where(conn, "feedback", uid, "outcome IS NOT NULL")
            engaged = owned_project_ids(conn, "interactions", uid)

            rows = conn.execute(
                """
                SELECT id, name, sector, stage, score, label, confidence, url, updated_at
                FROM projects
                WHERE label IN ('FARM', 'WATCH')
                ORDER BY score DESC
                LIMIT 400
                """
            ).fetchall()

        items: list[dict[str, Any]] = []
        for row in rows:
            pid = str(row["id"])
            if pid in done:
                continue
            has_interaction = pid in engaged
            items.append(
                {
                    "project_id": pid,
                    "name": row["name"],
                    "sector": row["sector"],
                    "stage": row["stage"],
                    "score": row["score"],
                    "label": row["label"],
                    "confidence": row["confidence"],
                    "url": row["url"],
                    "updated_at": str(row["updated_at"]) if row["updated_at"] else None,
                    "has_interaction": has_interaction,
                    # 你真金白银投入过的项目，其结果对校准的价值最高
                    "priority_reason": "你有交互记录" if has_interaction else "高分待验证",
                }
            )

        # 有交互记录的排前面；同组内保持 SQL 的分数降序（sort 是稳定排序）
        items.sort(key=lambda x: 0 if x["has_interaction"] else 1)
        limited = items[:limit]

        return FeedbackResponse(
            data={
                "items": limited,
                "total_pending": len(items),
                "returned": len(limited),
                "already_marked": len(done),
            }
        )
    except Exception as e:
        logger.error("feedback.pending_review_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to get pending review list"},
        ) from e


@router.get(
    "/feedback/{project_id}",
    response_model=FeedbackResponse,
    summary="查询项目反馈",
    description="获取指定项目的所有用户反馈统计（非管理员仅返回自身反馈，管理员可查看全部或按用户过滤）。",
)
def get_feedback(
    project_id: str,
    req: Request,
    user_id: str | None = Query(None, description="用户标识过滤（仅管理员可用）"),
) -> FeedbackResponse:
    """查询项目反馈（行级隔离）。"""
    if not settings.enable_feedback_system:
        raise HTTPException(
            status_code=400,
            detail={"code": "FEEDBACK_DISABLED", "message": "Feedback system is disabled"},
        )

    current_user = get_current_user(req)
    scope_clause, scope_params = build_user_scope_filter(
        user_id=current_user["user_id"],
        role=current_user["role"],
        admin_filter_user_id=user_id,
    )

    sql = "SELECT * FROM feedback WHERE project_id = ?"
    params: list[Any] = [project_id]
    if scope_clause:
        sql += f" AND {scope_clause}"
        params.extend(scope_params)
    sql += " ORDER BY created_at DESC"

    try:
        with get_connection() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()

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
def submit_event(request: EventRequest, req: Request) -> FeedbackResponse:
    """提交隐式事件埋点。"""
    if not settings.enable_events_tracking:
        raise HTTPException(
            status_code=400,
            detail={"code": "EVENTS_DISABLED", "message": "Events tracking is disabled"},
        )

    current_user = get_current_user(req)
    if current_user["role"] == ROLE_ADMIN:
        uid = request.user_id or current_user["user_id"]
    elif current_user["user_id"] != "anonymous":
        uid = current_user["user_id"]
    else:
        uid = request.user_id or "anonymous"

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
                    uid,
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
            user_id=uid,
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


@router.get(
    "/events",
    response_model=FeedbackResponse,
    responses={
        400: {"model": ErrorResponse, "description": "事件系统未启用"},
        500: {"model": ErrorResponse, "description": "数据库错误"},
    },
    summary="查询隐式事件",
    description="查询用户行为事件埋点列表（非管理员仅返回自身埋点，管理员可查看全部或按用户过滤）。",
)
def list_events(
    req: Request,
    project_id: str | None = Query(None, max_length=64, description="项目 ID 筛选"),
    event_type: str | None = Query(None, max_length=32, description="事件类型筛选"),
    limit: int = Query(50, ge=1, le=200, description="返回条数"),
    offset: int = Query(0, ge=0, description="偏移量"),
    user_id: str | None = Query(None, description="用户标识过滤（仅管理员可用）"),
) -> FeedbackResponse:
    """查询行为事件列表（行级隔离）。"""
    if not settings.enable_events_tracking:
        raise HTTPException(
            status_code=400,
            detail={"code": "EVENTS_DISABLED", "message": "Events tracking is disabled"},
        )

    current_user = get_current_user(req)
    scope_clause, scope_params = build_user_scope_filter(
        user_id=current_user["user_id"],
        role=current_user["role"],
        admin_filter_user_id=user_id,
    )

    clauses: list[str] = []
    params: list[Any] = []

    if scope_clause:
        clauses.append(scope_clause)
        params.extend(scope_params)

    if project_id:
        clauses.append("project_id = ?")
        params.append(project_id)

    if event_type:
        clauses.append("event_type = ?")
        params.append(event_type)

    where_sql = f" WHERE {' AND '.join(clauses)}" if clauses else ""

    try:
        with get_connection() as conn:
            count_row = conn.execute(
                f"SELECT COUNT(*) FROM events{where_sql}",  # noqa: S608
                tuple(params),
            ).fetchone()
            total = int(count_row[0]) if count_row else 0

            query_sql = f"""
                SELECT id, project_id, user_id, event_type, detail, timestamp
                FROM events
                {where_sql}
                ORDER BY timestamp DESC, id DESC
                LIMIT ? OFFSET ?
            """  # noqa: S608
            rows = conn.execute(query_sql, tuple(params + [limit, offset])).fetchall()
            items = [dict(row) for row in rows]

        return FeedbackResponse(
            data={
                "items": items,
                "total": total,
                "limit": limit,
                "offset": offset,
            }
        )
    except Exception as e:
        logger.error("event.list_failed", error=str(e), exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={"code": "DB_ERROR", "message": "Failed to list events"},
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
            signal_rows = conn.execute("SELECT signal, COUNT(*) as cnt FROM feedback GROUP BY signal").fetchall()
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
                metrics: dict[str, Any] = {}
                # 单条 metrics_json 损坏不该让整个 changelog 接口失败
                with contextlib.suppress(ValueError, TypeError):
                    metrics = _json.loads(row["metrics_json"]) if row["metrics_json"] else {}
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
