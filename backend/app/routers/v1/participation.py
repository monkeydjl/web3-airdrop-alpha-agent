"""Participation / farm task checklist for a project.

两块能力（ACTION_LOOP_DESIGN.md §3，F2）：

1. ``GET /projects/{id}/participation-tasks`` —— 无状态的**建议生成器**
   （原有），按项目信号产出优先级清单。
2. ``/participation`` 状态机端点 —— 服务端**参与流水**：plan/task 两级，
   按 user_id 隔离，替代前端 localStorage 勾选（勾选换设备即丢）。

身份边界：user_id 一律来自 token（``get_current_user``），**不接受请求体
自报** —— 本组端点对匿名 token 开放（与 feedback 同一设计意图：参与记录
本来就要让普通使用者写），接受客户端身份等于任何人都能读写别人的流水。
MVP 模式（API_KEY 为空）下统一记为 "anonymous"。

Reference:
- ADR-008-user-system.md
- docs/ACTION_LOOP_DESIGN.md §3
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import get_connection
from app.repository import ProjectRepository
from app.services.participation_tasks import generate_participation_tasks
from app.services.project_signals import signals_view

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["participation"])

# plan / task 状态机的合法迁移。收成闭表而不是散在 if 里：
# 新增状态必须先过这张表，否则前端会做出后端拒绝的交互。
_PLAN_TRANSITIONS: dict[str, set[str]] = {
    "active": {"paused", "completed", "abandoned"},
    "paused": {"active", "completed", "abandoned"},
    "completed": {"active"},  # 复盘后重新捡起来
    "abandoned": {"active"},
}

_TASK_TRANSITIONS: dict[str, set[str]] = {
    "todo": {"doing", "done", "skipped"},
    "doing": {"done", "skipped", "todo"},
    "done": {"todo"},  # 做错了允许重开
    "skipped": {"todo"},
}

_PLAN_STATUSES = set(_PLAN_TRANSITIONS)
_TASK_STATUSES = set(_TASK_TRANSITIONS)


# ═══════════════════════════════════════════════════════════════
# Request/Response Models
# ═══════════════════════════════════════════════════════════════


class ParticipationPlanCreate(BaseModel):
    """创建参与 plan 的请求。刻意没有 user_id 字段 —— 身份来自 token。"""

    seed_from_generated: bool = Field(
        default=True,
        description="把建议生成器的清单导入为可跟踪任务（按生成 id 去重）",
    )
    note: str | None = Field(default=None, max_length=500, description="参与动机/备注")


class ParticipationPlanPatch(BaseModel):
    """更新 plan 状态/备注。"""

    status: Literal["active", "paused", "completed", "abandoned"] | None = None
    note: str | None = Field(default=None, max_length=500)


class ParticipationTaskPatch(BaseModel):
    """更新任务状态/备注/截止时间。"""

    status: Literal["todo", "doing", "done", "skipped"] | None = None
    note: str | None = Field(default=None, max_length=500)
    due_at: str | None = Field(
        default=None,
        max_length=32,
        description="ISO 时间串（UTC）；传空串清除",
    )


def _plan_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "status": row["status"],
        "note": row["note"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _task_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "plan_id": row["plan_id"],
        "ref": row["ref"],
        "title": row["title"],
        "kind": row["kind"],
        "status": row["status"],
        "url": row["url"],
        "due_at": row["due_at"],
        "note": row["note"],
        "completed_at": row["completed_at"],
    }


def _get_owned_plan(conn: Any, plan_id: int, user_id: str) -> dict[str, Any]:
    """取 plan 并校验归属 —— 归属不对按 404 处理（不向试探者确认存在性）。"""
    row = conn.execute(
        "SELECT * FROM participation_plans WHERE id = ? AND user_id = ?",
        (plan_id, user_id),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Participation plan {plan_id} not found"},
        )
    return dict(row)


# ═══════════════════════════════════════════════════════════════
# 状态机端点（F2）
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/participation",
    summary="开始参与一个项目（创建 plan）",
    description=("按 user_id 隔离，同项目重复创建返回 409。`seed_from_generated=true` 时把建议清单导入为可跟踪任务。"),
)
def create_participation_plan(
    project_id: str,
    request: Request,
    body: ParticipationPlanCreate | None = None,
) -> dict[str, Any]:
    """创建参与 plan。user_id 来自 token，不是请求体。"""
    user = get_current_user(request)
    seed = bool(body.seed_from_generated) if body else True
    note = body.note if body else None

    with get_connection() as conn:
        project = conn.execute(
            "SELECT id FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
        if project is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
            )

        existing = conn.execute(
            "SELECT id FROM participation_plans WHERE user_id = ? AND project_id = ?",
            (user["user_id"], project_id),
        ).fetchone()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail={"code": "ALREADY_EXISTS", "message": f"Already participating in {project_id}"},
            )

        # RETURNING 而非 lastrowid：psycopg3 没有 lastrowid（db.py 有注释），
        # SQLite 3.35+ 支持 RETURNING —— 项目要求的 Python 3.11 自带 3.37+。
        row = conn.execute(
            """
            INSERT INTO participation_plans (user_id, project_id, status, note)
            VALUES (?, ?, 'active', ?)
            RETURNING id
            """,
            (user["user_id"], project_id, note),
        ).fetchone()
        plan_id = int(row["id"])
        seeded = 0
        if seed:
            seeded = _seed_tasks_from_generator(conn, plan_id, project_id)

        conn.commit()

    logger.info(
        "participation.plan_created",
        project_id=project_id,
        plan_id=plan_id,
        seeded=seeded,
    )
    return {
        "ok": True,
        "data": {"plan_id": plan_id, "project_id": project_id, "seeded_tasks": seeded},
    }


def _seed_tasks_from_generator(conn: Any, plan_id: int, project_id: str) -> int:
    """把建议生成器的清单导入为任务，按 (plan_id, ref) 去重。

    注意沿用 ``GET /participation-tasks`` 的教训：必须走 ``signals_view``，
    直接传 dict(project) 会让扩展信号恒为 False，清单退化成通用套话。
    """
    project = ProjectRepository().get_by_id(project_id)
    if not project:
        return 0
    generated = generate_participation_tasks(signals_view(project))
    items = generated.get("tasks") or []

    existing_refs = {
        row["ref"]
        for row in conn.execute(
            "SELECT ref FROM participation_tasks WHERE plan_id = ? AND ref IS NOT NULL",
            (plan_id,),
        ).fetchall()
    }
    seeded = 0
    for item in items:
        ref = str(item.get("id") or "")
        if not ref or ref in existing_refs:
            continue
        conn.execute(
            """
            INSERT INTO participation_tasks (plan_id, ref, title, kind, status, url)
            VALUES (?, ?, ?, ?, 'todo', ?)
            """,
            (
                plan_id,
                ref,
                str(item.get("title") or ref),
                str(item.get("category") or "other"),
                item.get("link"),
            ),
        )
        existing_refs.add(ref)
        seeded += 1
    return seeded


@router.get(
    "/participation",
    summary="我的全部参与 plan（含任务）",
    description="按 user_id 隔离，只返回当前 token 名下的 plan。",
)
def list_participation_plans(
    request: Request,
    status: Literal["active", "paused", "completed", "abandoned"] | None = None,
) -> dict[str, Any]:
    """列出我的 plan，按创建时间倒序，附任务清单。"""
    user = get_current_user(request)

    query = "SELECT * FROM participation_plans WHERE user_id = ?"
    params: list[Any] = [user["user_id"]]
    if status is not None:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY id DESC"

    with get_connection() as conn:
        plans = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]
        out: list[dict[str, Any]] = []
        for plan in plans:
            tasks = [
                _task_row_to_dict(r)
                for r in conn.execute(
                    "SELECT * FROM participation_tasks WHERE plan_id = ? ORDER BY id",
                    (plan["id"],),
                ).fetchall()
            ]
            entry = _plan_row_to_dict(plan)
            entry["tasks"] = tasks
            out.append(entry)

    return {"ok": True, "data": {"items": out, "count": len(out)}}


@router.patch(
    "/participation/{plan_id}",
    summary="更新参与 plan（状态机）",
    description="合法迁移：active↔paused、→completed/abandoned、completed→active。非法迁移 422。",
)
def patch_participation_plan(
    plan_id: int,
    body: ParticipationPlanPatch,
    request: Request,
) -> dict[str, Any]:
    """更新 plan；status 迁移必须落在 _PLAN_TRANSITIONS 闭表内。"""
    user = get_current_user(request)

    with get_connection() as conn:
        plan = _get_owned_plan(conn, plan_id, user["user_id"])

        updates: list[str] = ["updated_at = ?"]
        params: list[Any] = [_now_str()]
        if body.status is not None and body.status != plan["status"]:
            allowed = _PLAN_TRANSITIONS.get(str(plan["status"]), set())
            if body.status not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_TRANSITION",
                        "message": f"plan: {plan['status']} → {body.status} 不合法（允许 {sorted(allowed)}）",
                    },
                )
            updates.append("status = ?")
            params.append(body.status)
        if body.note is not None:
            updates.append("note = ?")
            params.append(body.note)

        # SET 片段只来自闭表白名单字面量（status/note/updated_at），值全部参数化
        conn.execute(
            f"UPDATE participation_plans SET {', '.join(updates)} WHERE id = ?",  # noqa: S608
            (*params, plan_id),
        )
        conn.commit()

    logger.info("participation.plan_updated", plan_id=plan_id)
    return {"ok": True, "data": {"plan_id": plan_id}}


@router.patch(
    "/participation/tasks/{task_id}",
    summary="更新参与任务（状态机）",
    description="合法迁移见 _TASK_TRANSITIONS；done 时自动记 completed_at，重开时清除。",
)
def patch_participation_task(
    task_id: int,
    body: ParticipationTaskPatch,
    request: Request,
) -> dict[str, Any]:
    """更新任务；plan 归属校验同 plan 级（不匹配 404）。"""
    user = get_current_user(request)

    with get_connection() as conn:
        owned = conn.execute(
            """
            SELECT t.id FROM participation_tasks t
            JOIN participation_plans p ON p.id = t.plan_id
            WHERE t.id = ? AND p.user_id = ?
            """,
            (task_id, user["user_id"]),
        ).fetchone()
        if owned is None:
            _not_found(task_id)

        row = conn.execute(
            "SELECT * FROM participation_tasks WHERE id = ?",
            (task_id,),
        ).fetchone()
        task = dict(row)

        updates: list[str] = []
        params: list[Any] = []
        if body.status is not None and body.status != task["status"]:
            allowed = _TASK_TRANSITIONS.get(str(task["status"]), set())
            if body.status not in allowed:
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": "INVALID_TRANSITION",
                        "message": f"task: {task['status']} → {body.status} 不合法（允许 {sorted(allowed)}）",
                    },
                )
            updates.append("status = ?")
            params.append(body.status)
            if body.status == "done":
                updates.append("completed_at = ?")
                params.append(_now_str())
            elif task["status"] == "done":
                updates.append("completed_at = NULL")
        if body.note is not None:
            updates.append("note = ?")
            params.append(body.note)
        if body.due_at is not None:
            updates.append("due_at = ?")
            params.append(body.due_at or None)

        if updates:
            # 同上：SET 片段闭表白名单，值参数化
            conn.execute(
                f"UPDATE participation_tasks SET {', '.join(updates)} WHERE id = ?",  # noqa: S608
                (*params, task_id),
            )
            conn.commit()

    logger.info("participation.task_updated", task_id=task_id)
    return {"ok": True, "data": {"task_id": task_id}}


@router.delete(
    "/participation/{plan_id}",
    summary="删除参与 plan（级联删任务）",
)
def delete_participation_plan(plan_id: int, request: Request) -> dict[str, Any]:
    user = get_current_user(request)
    with get_connection() as conn:
        _get_owned_plan(conn, plan_id, user["user_id"])
        conn.execute("DELETE FROM participation_tasks WHERE plan_id = ?", (plan_id,))
        conn.execute("DELETE FROM participation_plans WHERE id = ?", (plan_id,))
        conn.commit()
    logger.info("participation.plan_deleted", plan_id=plan_id)
    return {"ok": True, "data": {"plan_id": plan_id, "deleted": True}}


def _not_found(task_id: int) -> None:
    raise HTTPException(
        status_code=404,
        detail={"code": "NOT_FOUND", "message": f"Participation task {task_id} not found"},
    )


def _now_str() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════
# 建议生成器（原有，无状态）
# ═══════════════════════════════════════════════════════════════


@router.get("/projects/{project_id}/participation-tasks")
def get_participation_tasks(
    project_id: str = Path(..., description="项目 ID"),
) -> dict[str, Any]:
    """Return a prioritized checklist of things a user can do for this project."""
    repo = ProjectRepository()
    project = repo.get_by_id(project_id)
    if not project:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )

    # 必须走 signals_view：扩展信号存在 meta.signals 里，projects 表没有对应列，
    # 直接传 dict(project) 会让全部信号判断恒为 False（任务清单退化为通用套话）。
    data = generate_participation_tasks(signals_view(project))
    logger.info(
        "participation.tasks_generated",
        project_id=project_id,
        task_count=data.get("summary", {}).get("total"),
    )
    return {"ok": True, "data": data}
