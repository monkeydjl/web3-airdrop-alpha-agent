"""管理员写操作安全审计服务（audit_logs 表生产写入与查询）。

所有命中 `requires_admin(method, path)` 的成功写操作（POST/PUT/PATCH/DELETE 且 2xx/3xx）
均经由本模块落库至 `audit_logs`，写入前强制通过 `app.utils.redact.redact` 脱敏，
并由 `RawDataArchiver.prune_audit_logs` 按 365 天保留期定时修剪。
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from app.db import DbConnection, connection_scope
from app.repositories.v2 import AuditLogRepository
from app.utils.redact import redact

logger = structlog.get_logger(__name__)

_MAX_DETAIL_CHARS = 4000


def _serialize_detail(detail: dict[str, Any] | str | None) -> str | None:
    if detail is None:
        return None
    raw = (
        json.dumps(detail, ensure_ascii=False, sort_keys=True, default=str) if isinstance(detail, dict) else str(detail)
    )
    masked = redact(raw)
    if len(masked) > _MAX_DETAIL_CHARS:
        return masked[:_MAX_DETAIL_CHARS] + "...(truncated)"
    return masked


def record_admin_audit(
    *,
    action: str,
    user: str,
    detail: dict[str, Any] | str | None = None,
    ip: str | None = None,
    conn: DbConnection | None = None,
) -> int:
    """持久化一条管理员写操作审计记录（已脱敏）。"""
    safe_action = redact(action.strip())[:200]
    safe_user = redact(user.strip() or "unknown")[:120]
    safe_detail = _serialize_detail(detail)
    safe_ip = redact(ip.strip())[:64] if ip else None

    with connection_scope(conn) as db_conn:
        return AuditLogRepository(db_conn).insert(
            action=safe_action,
            user=safe_user,
            detail=safe_detail,
            ip=safe_ip,
        )


def safe_record_admin_audit(
    *,
    action: str,
    user: str,
    detail: dict[str, Any] | str | None = None,
    ip: str | None = None,
    conn: DbConnection | None = None,
) -> int:
    """最佳努力写入审计日志：落库异常仅记结构化告警，不阻断主业务响应。"""
    try:
        return record_admin_audit(
            action=action,
            user=user,
            detail=detail,
            ip=ip,
            conn=conn,
        )
    except Exception as exc:
        logger.warning(
            "api.audit_log_failed",
            action=redact(action)[:120],
            error_type=type(exc).__name__,
            error=redact(str(exc))[:200],
        )
        return 0


def list_admin_audit_logs(
    *,
    action: str | None = None,
    user: str | None = None,
    limit: int = 100,
    conn: DbConnection | None = None,
) -> list[dict[str, Any]]:
    """按条件倒序查询管理员安全审计日志。"""
    capped_limit = max(1, min(int(limit), 500))
    clean_action = action.strip() if action and action.strip() else None
    clean_user = user.strip() if user and user.strip() else None

    with connection_scope(conn) as db_conn:
        return AuditLogRepository(db_conn).query(
            action=clean_action,
            user=clean_user,
            limit=capped_limit,
        )
