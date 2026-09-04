"""ROI ledger / 收益台账 for a project（F3，ACTION_LOOP_DESIGN §4）。

结构化记录「投入了什么 / 拿回了什么」，用来给权重校准提供**真值**：

- ``roi_entries``  = 投入（gas / infra / time / other）
- ``roi_outcomes`` = 产出（token_launched / airdrop_received /
  airdrop_missed / campaign_ended）

为什么需要它：反馈只有 ``useful / useless / wrong_label / correct_outcome``
四档主观信号，校准（有效样本 ≥200 / FARM ≥30 门槛）学到的是「用户觉得对不对」，
学不到「最后到底有没有领到钱」。台账补的是后者。

**诚实边界**（§4.2，别在代码里偷偷越线）：
- ``amount_usd`` 以人工录入为准，MVP 不做链上自动取价 —— 代币价格源是另一个工程。
- ``tx_hash`` 只是凭证存档，不自动验证。把它当"已确权"是虚假的确权感。
- 汇总**不给时间定价**。`hours` 原样返回，不折算成美元 —— 折算要引入一个
  凭空捏造的时薪，那会让 ROI 数字看起来精确但不可信。

身份边界：user_id 一律来自 token（``get_current_user``），**不接受请求体自报**
—— 2026-08-30 审核 P1-1 的同款教训。归属不匹配的资源按 404 处理，
不向试探者确认存在性。

Reference:
- docs/ACTION_LOOP_DESIGN.md §4
- app/calibration.py（source 分桶消费本表产出）
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.auth import get_current_user
from app.db import get_connection

logger = structlog.get_logger(__name__)
router = APIRouter(tags=["roi"])

# 投入类型。time 单独一类是因为早期参与的绝大成本是时间不是 gas ——
# 只记金额会让台账系统性低估投入，进而把 ROI 算得过分乐观。
ENTRY_KINDS = ("gas", "infra", "time", "other")

# 产出事件。airdrop_missed 与 airdrop_received 是校准的正负样本来源。
OUTCOME_EVENTS = (
    "token_launched",
    "airdrop_received",
    "airdrop_missed",
    "campaign_ended",
)

# 样本来源。manual 即「真实操作留痕」，校准侧映射为 live 桶；
# backtest 是历史回测导出（§4.3 两类样本分开统计，不混算）。
OUTCOME_SOURCES = ("manual", "backtest")

_ROI_TABLES = {"entries": "roi_entries", "outcomes": "roi_outcomes"}


# ═══════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════


class RoiEntryCreate(BaseModel):
    """记一笔投入。刻意没有 user_id 字段 —— 身份来自 token。"""

    kind: Literal["gas", "infra", "time", "other"] = Field(
        default="other",
        description="投入类型",
    )
    amount_usd: float | None = Field(default=None, ge=0, description="金钱投入（美元）")
    hours: float | None = Field(default=None, ge=0, description="时间投入（小时）")
    note: str | None = Field(default=None, max_length=500)


class RoiOutcomeCreate(BaseModel):
    """记一笔产出。"""

    event: Literal[
        "token_launched",
        "airdrop_received",
        "airdrop_missed",
        "campaign_ended",
    ] = Field(description="产出事件类型")
    amount_usd: float | None = Field(default=None, ge=0, description="估值（人工录入）")
    tokens: float | None = Field(default=None, ge=0, description="代币数量")
    tx_hash: str | None = Field(default=None, max_length=128, description="凭证存档，不自动验证")
    source: Literal["manual", "backtest"] = Field(
        default="manual",
        description="样本来源：manual=真实留痕（校准侧 live 桶）/ backtest=回测导出",
    )
    note: str | None = Field(default=None, max_length=500)


def _entry_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "kind": row["kind"],
        "amount_usd": row["amount_usd"],
        "hours": row["hours"],
        "note": row["note"],
        "recorded_at": row["recorded_at"],
    }


def _outcome_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "event": row["event"],
        "amount_usd": row["amount_usd"],
        "tokens": row["tokens"],
        "tx_hash": row["tx_hash"],
        "source": row["source"],
        "recorded_at": row["recorded_at"],
    }


def _not_found(kind: str, record_id: int) -> None:
    raise HTTPException(
        status_code=404,
        detail={"code": "NOT_FOUND", "message": f"ROI {kind[:-1]} {record_id} not found"},
    )


def _require_amount(entry: RoiEntryCreate) -> None:
    """投入至少要有一个量纲，否则这行账没有信息。"""
    if entry.amount_usd is None and entry.hours is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "MISSING_AMOUNT",
                "message": "amount_usd 与 hours 至少要填一个 —— 两个都空的行对台账没有贡献",
            },
        )


def _safe_div(numerator: float, denominator: float) -> float | None:
    """除零返回 None 而不是 0 或 inf。

    零投入下的「ROI」没有定义；返回 0 会让人以为「没赚没赔」，
    返回 inf 会污染任何下游聚合。None 逼调用方显式处理这个边界。
    """
    if denominator <= 0:
        return None
    return numerator / denominator


# ═══════════════════════════════════════════════════════════════
# 录入
# ═══════════════════════════════════════════════════════════════


@router.post(
    "/projects/{project_id}/roi/entries",
    summary="记一笔投入（gas/基础设施/时间）",
    description="按 user_id 隔离。amount_usd 与 hours 至少填一个。",
)
def create_roi_entry(
    project_id: str,
    body: RoiEntryCreate,
    request: Request,
) -> dict[str, Any]:
    """写入一行 roi_entries。"""
    user = get_current_user(request)
    _require_amount(body)

    with get_connection() as conn:
        _require_project(conn, project_id)
        # RETURNING 而非 lastrowid：psycopg3 没有 lastrowid（db.py 有注释）。
        row = conn.execute(
            """
            INSERT INTO roi_entries (user_id, project_id, kind, amount_usd, hours, note)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (user["user_id"], project_id, body.kind, body.amount_usd, body.hours, body.note),
        ).fetchone()
        entry_id = int(row["id"])
        conn.commit()

    logger.info("roi.entry_recorded", project_id=project_id, entry_id=entry_id, kind=body.kind)
    return {"ok": True, "data": {"entry_id": entry_id, "project_id": project_id}}


@router.post(
    "/projects/{project_id}/roi/outcomes",
    summary="记一笔产出（空投到账/未领取/发币/活动结束）",
    description="airdrop_received / airdrop_missed 是校准的正负样本来源。",
)
def create_roi_outcome(
    project_id: str,
    body: RoiOutcomeCreate,
    request: Request,
) -> dict[str, Any]:
    """写入一行 roi_outcomes。"""
    user = get_current_user(request)

    with get_connection() as conn:
        _require_project(conn, project_id)
        row = conn.execute(
            """
            INSERT INTO roi_outcomes
                (user_id, project_id, event, amount_usd, tokens, tx_hash, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                user["user_id"],
                project_id,
                body.event,
                body.amount_usd,
                body.tokens,
                body.tx_hash,
                body.source,
            ),
        ).fetchone()
        outcome_id = int(row["id"])
        conn.commit()

    # ⚠️ 字段名叫 outcome_event 而不是 event：structlog 的调用签名是
    # `logger.info(event, *args, **kw)`，`event` 是位置参数名，当关键字传会
    # 直接 TypeError（got multiple values for argument 'event'）。
    # 这个坑只在运行时炸，静态扫描扫不出来。
    logger.info(
        "roi.outcome_recorded",
        project_id=project_id,
        outcome_id=outcome_id,
        outcome_event=body.event,
        source=body.source,
    )
    return {"ok": True, "data": {"outcome_id": outcome_id, "project_id": project_id}}


# ═══════════════════════════════════════════════════════════════
# 查询
# ═══════════════════════════════════════════════════════════════


@router.get(
    "/projects/{project_id}/roi",
    summary="该项目的投入产出明细与小计",
    description="按 user_id 隔离，只返回当前 token 名下记录。",
)
def get_project_roi(project_id: str, request: Request) -> dict[str, Any]:
    """返回明细 + 小计。小计同样不给时间定价。"""
    user = get_current_user(request)

    with get_connection() as conn:
        entries = [
            _entry_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM roi_entries WHERE user_id = ? AND project_id = ? ORDER BY id",
                (user["user_id"], project_id),
            ).fetchall()
        ]
        outcomes = [
            _outcome_row_to_dict(r)
            for r in conn.execute(
                "SELECT * FROM roi_outcomes WHERE user_id = ? AND project_id = ? ORDER BY id",
                (user["user_id"], project_id),
            ).fetchall()
        ]

    cost = _sum_field(entries, "amount_usd")
    hours = _sum_field(entries, "hours")
    returned = _sum_field(outcomes, "amount_usd")
    tokens = _sum_field(outcomes, "tokens")

    return {
        "ok": True,
        "data": {
            "project_id": project_id,
            "entries": entries,
            "outcomes": outcomes,
            "subtotal": {
                "cost_usd": round(cost, 4),
                "hours": round(hours, 4),
                "returned_usd": round(returned, 4),
                "tokens": round(tokens, 4),
                "net_usd": round(returned - cost, 4),
                "roi_ratio": _safe_div(returned - cost, cost),
            },
        },
    }


@router.get(
    "/roi/summary",
    summary="我的收益台账总览",
    description="跨项目汇总投入产出。hours 不折算成钱（不引入凭空捏造的时薪）。",
)
def get_roi_summary(request: Request) -> dict[str, Any]:
    """按 user_id 汇总全部投入产出，并按项目拆开。"""
    user = get_current_user(request)
    uid = user["user_id"]

    with get_connection() as conn:
        entry_rows = conn.execute(
            """
            SELECT project_id,
                   COALESCE(SUM(amount_usd), 0) AS cost_usd,
                   COALESCE(SUM(hours), 0)      AS hours
            FROM roi_entries
            WHERE user_id = ?
            GROUP BY project_id
            """,
            (uid,),
        ).fetchall()
        outcome_rows = conn.execute(
            """
            SELECT project_id,
                   COALESCE(SUM(amount_usd), 0) AS returned_usd,
                   COALESCE(SUM(tokens), 0)     AS tokens
            FROM roi_outcomes
            WHERE user_id = ?
            GROUP BY project_id
            """,
            (uid,),
        ).fetchall()

    cost_by_project = {r["project_id"]: float(r["cost_usd"]) for r in entry_rows}
    hours_by_project = {r["project_id"]: float(r["hours"]) for r in entry_rows}
    returned_by_project = {r["project_id"]: float(r["returned_usd"]) for r in outcome_rows}
    tokens_by_project = {r["project_id"]: float(r["tokens"]) for r in outcome_rows}

    projects = sorted(set(cost_by_project) | set(returned_by_project))
    items = []
    for pid in projects:
        cost = cost_by_project.get(pid, 0.0)
        returned = returned_by_project.get(pid, 0.0)
        items.append(
            {
                "project_id": pid,
                "cost_usd": round(cost, 4),
                "hours": round(hours_by_project.get(pid, 0.0), 4),
                "returned_usd": round(returned, 4),
                "tokens": round(tokens_by_project.get(pid, 0.0), 4),
                "net_usd": round(returned - cost, 4),
                "roi_ratio": _safe_div(returned - cost, cost),
            }
        )

    total_cost = sum(cost_by_project.values())
    total_returned = sum(returned_by_project.values())
    net = total_returned - total_cost

    return {
        "ok": True,
        "data": {
            "totals": {
                "cost_usd": round(total_cost, 4),
                "hours": round(sum(hours_by_project.values()), 4),
                "returned_usd": round(total_returned, 4),
                "tokens": round(sum(tokens_by_project.values()), 4),
                "net_usd": round(net, 4),
                "roi_ratio": _safe_div(net, total_cost),
                "project_count": len(projects),
            },
            "items": items,
        },
    }


# ═══════════════════════════════════════════════════════════════
# 删除（录错了要能改）
# ═══════════════════════════════════════════════════════════════


@router.delete("/roi/entries/{entry_id}", summary="删除一条投入记录")
def delete_roi_entry(entry_id: int, request: Request) -> dict[str, Any]:
    """删自己的投入记录；不是自己的按 404。"""
    user = get_current_user(request)
    _delete_owned("entries", entry_id, user["user_id"])
    logger.info("roi.entry_deleted", entry_id=entry_id)
    return {"ok": True, "data": {"entry_id": entry_id, "deleted": True}}


@router.delete("/roi/outcomes/{outcome_id}", summary="删除一条产出记录")
def delete_roi_outcome(outcome_id: int, request: Request) -> dict[str, Any]:
    """删自己的产出记录；不是自己的按 404。"""
    user = get_current_user(request)
    _delete_owned("outcomes", outcome_id, user["user_id"])
    logger.info("roi.outcome_deleted", outcome_id=outcome_id)
    return {"ok": True, "data": {"outcome_id": outcome_id, "deleted": True}}


# ═══════════════════════════════════════════════════════════════
# 内部辅助
# ═══════════════════════════════════════════════════════════════


def _delete_owned(kind: str, record_id: int, user_id: str) -> None:
    """按 user_id 归属删除。表名来自闭表，值全部参数化。"""
    table = _ROI_TABLES[kind]
    with get_connection() as conn:
        cursor = conn.execute(
            f"DELETE FROM {table} WHERE id = ? AND user_id = ?",  # noqa: S608
            (record_id, user_id),
        )
        conn.commit()
    if not cursor.rowcount:
        _not_found(kind, record_id)


def _require_project(conn: Any, project_id: str) -> None:
    """投入产出必须挂在真实项目上。

    这里刻意校验：不校验的话台账里会塞进拼错的项目 id，聚合时静默丢失，
    而且校准样本会对不上任何 sub_scores（提取样本要 JOIN projects）。
    """
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "NOT_FOUND", "message": f"Project {project_id} not found"},
        )


def _sum_field(rows: list[dict[str, Any]], field: str) -> float:
    """对明细行求和，None 当 0 —— SQL SUM 的 COALESCE 语义在这层保持一致。"""
    return sum(float(r.get(field) or 0.0) for r in rows)
