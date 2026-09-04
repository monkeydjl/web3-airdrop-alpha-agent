"""决策推送端点（ACTION_LOOP_DESIGN.md §2.7，管理员专用）。

整个前缀在 `auth.ADMIN_ONLY_PREFIXES` 里：通道配置与发送历史属于运维情报
（目的地、发送频率、失败原因），对匿名角色开放等于免费送侦察。

错误响应用 JSONResponse 显式携带状态码 —— 与 webhook.py 同一口径
（`{ok: false, error: {code, message}}`），而不是让 FastAPI 默认 200。

Reference:
- docs/ACTION_LOOP_DESIGN.md §2
- app/notify/（评估器 / 发送器 / 服务层）
"""

from __future__ import annotations

from typing import Any, Literal

import structlog
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.config import settings
from app.db import get_connection
from app.notify.senders import get_sender

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["notify"])


def _ok(data: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "error": {"code": code, "message": message}},
    )


@router.post(
    "/notify/test",
    summary="发送测试推送",
    description="按当前配置向通知通道发一条测试消息，验证凭证与连通性。",
)
async def send_test_notification() -> Any:
    """发一条测试消息；通道未配置时 503（与 webhook 未配置同口径，fail-closed）。"""
    try:
        sender = get_sender()
    except RuntimeError as exc:
        return _error(503, "NOTIFY_NOT_CONFIGURED", str(exc))

    try:
        await sender.send("测试推送", "如果你看到这条消息，决策推送通道已就绪。")
    except Exception as exc:
        logger.warning("notify.test_send_failed", channel=sender.channel, error=str(exc)[:200])
        return _error(502, "NOTIFY_SEND_FAILED", f"测试消息发送失败：{exc}"[:300])

    return _ok({"sent": True, "channel": sender.channel})


@router.get(
    "/notify/status",
    summary="推送通道状态",
    description="回显配置布尔与 cron，不回显任何凭证值。",
)
def notify_status() -> dict[str, Any]:
    """通道就绪状态的布尔回显（与 /webhook/alchemy/status 同一克制口径）。"""
    return _ok(
        {
            "enabled": settings.notify_enabled,
            "channel": settings.notify_channel,
            "telegram_configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
            "discord_configured": bool(settings.discord_notify_webhook_url),
            "digest_cron": settings.notify_digest_cron,
            "max_per_run": settings.notify_max_per_run,
        }
    )


@router.get(
    "/notify/log",
    summary="推送发送历史",
    description="出站日志（分页，新→旧），含失败原因，供排查「为什么没收到推送」。",
)
def notify_log(
    limit: int = Query(default=50, ge=1, le=200),
    status: Literal["pending", "sent", "failed"] | None = Query(default=None),
) -> dict[str, Any]:
    """发送历史，新→旧。status 非法值由 FastAPI 自动 422。"""
    query = (
        "SELECT id, event_type, event_key, channel, title, status, attempts, "
        "last_error, created_at, sent_at FROM notify_log"
    )
    params: list[Any] = []
    if status:
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with get_connection() as conn:
        rows = [dict(r) for r in conn.execute(query, tuple(params)).fetchall()]

    return _ok({"items": rows, "count": len(rows)})
