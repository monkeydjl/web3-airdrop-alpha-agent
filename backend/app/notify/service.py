"""决策推送服务层：评估 → 去重入库 → 发送（ACTION_LOOP_DESIGN.md §2）。

入口只有两个，调用方不需要知道更多：

- `run_daily_digest()` —— 每日摘要 cron job（UnifiedScheduler 的 notify_digest）。
- `evaluate_after_run()` —— pipeline 收尾钩子（score_crossing / new_farm /
  watchlist_signal）。

「至少一次评估、至多一次发送」由 notify_log 的 `(event_key, channel)` 唯一
约束保证：评估可以重复跑，入库 UPSERT DO NOTHING，发送只挑 `pending` 行。
发送是尽力而为：重试 ≤3 次后置 `failed` 不再自动重发，失败的行留在表里
供 `/api/v1/notify/log` 排查。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import structlog

from app.config import settings
from app.db import get_connection
from app.metrics import (
    NOTIFY_EVENT_TYPES,
    NOTIFY_EVENTS_EVALUATED,
    NOTIFY_FAILURES,
    NOTIFY_SENT,
)
from app.notify.evaluator import NotifyEvent, evaluate_events
from app.notify.senders import get_sender

logger = structlog.get_logger(__name__)

# 发送重试上限；超过后 status=failed，不再自动重发（人工排查后可手动重发）
MAX_SEND_ATTEMPTS = 3


def insert_event(conn: Any, event: NotifyEvent, channel: str) -> bool:
    """事件入库（同 event_key+channel 忽略）。返回是否新插入。"""
    if event.event_type not in NOTIFY_EVENT_TYPES:
        # 词表闭合：新事件类型必须先登记进 metrics.NOTIFY_EVENT_TYPES，
        # 否则 Prometheus 里会出现没人定义过的标签值。
        raise ValueError(f"unknown notify event_type: {event.event_type!r}")
    cursor = conn.execute(
        """
        INSERT INTO notify_log (event_type, event_key, channel, title, body)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (event_key, channel) DO NOTHING
        """,
        (event.event_type, event.event_key, channel, event.title, event.body),
    )
    return bool(cursor.rowcount and cursor.rowcount > 0)


def _pending_rows(conn: Any, channel: str, limit: int) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT id, title, body, attempts
        FROM notify_log
        WHERE status = 'pending' AND channel = ?
        ORDER BY id
        LIMIT ?
        """,
        (channel, limit),
    )
    return [dict(r) for r in cursor.fetchall()]


def _mark_sent(conn: Any, row_id: int) -> None:
    conn.execute(
        "UPDATE notify_log SET status = 'sent', sent_at = ?, attempts = attempts + 1 WHERE id = ?",
        (datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S"), row_id),
    )


def _mark_failed(conn: Any, row_id: int, attempts: int, error: str) -> None:
    status = "failed" if attempts + 1 >= MAX_SEND_ATTEMPTS else "pending"
    conn.execute(
        "UPDATE notify_log SET status = ?, attempts = ?, last_error = ? WHERE id = ?",
        (status, attempts + 1, error[:400], row_id),
    )


async def dispatch_pending(*, limit: int | None = None) -> dict[str, int]:
    """把 pending 的事件经配置通道发出去。返回 {sent, failed}。"""
    channel = settings.notify_channel
    sender = get_sender()
    effective_limit = limit if limit is not None else settings.notify_max_per_run

    def _load() -> list[dict[str, Any]]:
        with get_connection() as conn:
            return _pending_rows(conn, channel, effective_limit)

    # 同步 DB 读移出事件循环（2026-08-30 审核 P1-4 的同款教训）
    rows = await asyncio.to_thread(_load)

    sent = failed = 0
    for row in rows:
        try:
            await sender.send(str(row["title"]), str(row["body"]))
        except Exception as exc:
            error = str(exc)
            attempts = int(row.get("attempts") or 0)

            def _record_failure(row_id: int = int(row["id"]), a: int = attempts, err: str = error) -> None:
                with get_connection() as conn:
                    _mark_failed(conn, row_id, a, err)
                    conn.commit()

            await asyncio.to_thread(_record_failure)
            NOTIFY_FAILURES.labels(channel=channel).inc()
            failed += 1
            logger.warning("notify.send_failed", channel=channel, row_id=row["id"], error=error[:200])
        else:

            def _record_sent(row_id: int = int(row["id"])) -> None:
                with get_connection() as conn:
                    _mark_sent(conn, row_id)
                    conn.commit()

            await asyncio.to_thread(_record_sent)
            NOTIFY_SENT.labels(channel=channel).inc()
            sent += 1

    logger.info("notify.dispatch_completed", channel=channel, sent=sent, failed=failed)
    return {"sent": sent, "failed": failed}


def _collect_and_store(*, include_digest: bool) -> int:
    """同步评估 + 入库，返回新入队的行数。"""
    with get_connection() as conn:
        events = evaluate_events(conn, include_digest=include_digest)
        inserted = 0
        for event in events:
            if insert_event(conn, event, settings.notify_channel):
                inserted += 1
        conn.commit()
        for event in events:
            NOTIFY_EVENTS_EVALUATED.labels(event_type=event.event_type).inc()
        return inserted


async def evaluate_after_run(*, trigger: str) -> dict[str, int]:
    """pipeline 收尾钩子：评估跨线 / 新 FARM / 观察列表信号（不含摘要）。

    任何异常都吞掉只记 warning —— 推送链路绝不能影响评分主链路
    （与 opportunity shadow 同一口径）。
    """
    try:
        inserted = await asyncio.to_thread(_collect_and_store, include_digest=False)
        logger.info(
            "notify.after_run_completed",
            trigger=trigger,
            new_events=inserted,
            notify_enabled=settings.notify_enabled,
        )
        if settings.notify_enabled and inserted:
            return await dispatch_pending()
        return {"sent": 0, "failed": 0, "queued": inserted}
    except Exception as exc:
        logger.warning("notify.after_run_failed", trigger=trigger, error=str(exc)[:200])
        return {"sent": 0, "failed": 0}


async def run_daily_digest() -> dict[str, int]:
    """每日摘要 job 入口：摘要 + 全量事件评估，然后按开关决定是否发送。"""
    inserted = await asyncio.to_thread(_collect_and_store, include_digest=True)
    if not settings.notify_enabled:
        # 评估照跑（notify_log 留痕、指标可见），只是不发 —— 关开关 ≠ 停审计
        logger.info("notify.disabled_skip_send", new_events=inserted)
        return {"sent": 0, "failed": 0, "queued": inserted}
    result = await dispatch_pending()
    result["queued"] = inserted
    return result
