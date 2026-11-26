"""Multi-source free signal correlation & consensus engine.

Aggregates signals from Telegram, Farcaster, GitHub, RSS, and other free sources
to cross-verify project mentions without paying external commercial API fees or LLM tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import DbConnection, connection_scope


def calculate_consensus(signals: list[dict[str, Any]]) -> dict[str, Any]:
    """Calculate multi-source consensus metrics from a list of raw signal dicts.

    Each signal dict is expected to have keys:
    - signal_source: str
    - signal_type: str
    - signal_strength: float (optional)
    - captured_at: str | datetime (optional)
    """
    if not signals:
        return {
            "source_count": 0,
            "sources": [],
            "signal_types": [],
            "total_signals": 0,
            "consensus_tier": "none",
            "consensus_tier_zh": "暂无独立源",
            "has_testnet_consensus": False,
            "free_alpha_boost": 0.0,
        }

    sources_set: set[str] = set()
    signal_types_set: set[str] = set()
    testnet_sources: set[str] = set()

    for s in signals:
        src = str(s.get("signal_source") or "").strip().lower()
        stype = str(s.get("signal_type") or "").strip().lower()
        if src:
            sources_set.add(src)
        if stype:
            signal_types_set.add(stype)
        if ("testnet" in stype or "testnet" in str(s.get("signal_data") or "").lower()) and src:
            testnet_sources.add(src)

    sources = sorted(sources_set)
    signal_types = sorted(signal_types_set)
    source_count = len(sources)

    if source_count >= 3:
        tier = "high"
        tier_zh = "多源高度共识"
        boost = 0.15
    elif source_count == 2:
        tier = "medium"
        tier_zh = "双源交叉印证"
        boost = 0.08
    elif source_count == 1:
        tier = "single"
        tier_zh = "单源情报"
        boost = 0.02
    else:
        tier = "none"
        tier_zh = "暂无独立源"
        boost = 0.0

    # Testnet consensus: reported by at least 2 distinct sources, or by 1 source if total source_count >= 2
    has_testnet_consensus = len(testnet_sources) >= 2 or (len(testnet_sources) >= 1 and source_count >= 2)

    return {
        "source_count": source_count,
        "sources": sources,
        "signal_types": signal_types,
        "total_signals": len(signals),
        "consensus_tier": tier,
        "consensus_tier_zh": tier_zh,
        "has_testnet_consensus": has_testnet_consensus,
        "free_alpha_boost": boost,
    }


def correlate_signals_for_project(
    conn: DbConnection | None = None,
    project_id: str = "",
    window_days: int = 14,
) -> dict[str, Any]:
    """Calculate consensus for a specific project within the time window."""
    if not project_id:
        return calculate_consensus([])

    with connection_scope(conn) as c:
        since_dt = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
        cursor = c.execute(
            """
            SELECT signal_source, signal_type, signal_strength, captured_at, signal_data
            FROM project_signals
            WHERE project_id = ? AND captured_at >= ?
            ORDER BY captured_at DESC
            """,
            (project_id, since_dt),
        )
        rows = cursor.fetchall()
        signals: list[dict[str, Any]] = []
        for r in rows:
            # support dict or tuple row
            if isinstance(r, dict) or hasattr(r, "keys"):
                signals.append(dict(r))
            else:
                signals.append(
                    {
                        "signal_source": r[0],
                        "signal_type": r[1],
                        "signal_strength": r[2],
                        "captured_at": r[3],
                        "signal_data": r[4],
                    }
                )
        return calculate_consensus(signals)


def batch_correlate_signals(
    conn: DbConnection | None = None,
    window_days: int = 14,
    project_ids: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Batch correlate project signals within the window in a single query.

    Args:
        conn: 注入连接（None 时自建）。
        window_days: 一致性统计窗口（天）。
        project_ids: 可选限定项目集合（list_projects 分页用）——None = 全库；
            空列表 = 直接返回空表（不发查询）。

    列表路径**必须**走这里，而不是逐行 `correlate_signals_for_project`
    （page_size 上限 500 即 500 次查询/请求，2026-11-13 审查 P2-2）。
    """
    if project_ids is not None and not project_ids:
        return {}

    with connection_scope(conn) as c:
        since_dt = (datetime.now(UTC) - timedelta(days=window_days)).isoformat()
        if project_ids is not None:
            # 占位符由内部常量拼接，id 值全走绑定参数
            placeholders = ",".join("?" for _ in project_ids)
            sql = f"""
                SELECT project_id, signal_source, signal_type, signal_strength, captured_at, signal_data
                FROM project_signals
                WHERE project_id IN ({placeholders}) AND captured_at >= ?
            """  # noqa: S608
            params: list[Any] = [*project_ids, since_dt]
        else:
            sql = """
                SELECT project_id, signal_source, signal_type, signal_strength, captured_at, signal_data
                FROM project_signals
                WHERE project_id IS NOT NULL AND project_id != '' AND captured_at >= ?
            """
            params = [since_dt]
        cursor = c.execute(sql, params)
        rows = cursor.fetchall()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            if isinstance(r, dict):
                pid = r.get("project_id")
                item = dict(r)
            elif hasattr(r, "keys"):
                d = dict(r)
                pid = d.get("project_id")
                item = d
            else:
                pid = r[0]
                item = {
                    "signal_source": r[1],
                    "signal_type": r[2],
                    "signal_strength": r[3],
                    "captured_at": r[4],
                    "signal_data": r[5] if len(r) > 5 else None,
                }
            if pid:
                grouped.setdefault(str(pid), []).append(item)

        out: dict[str, dict[str, Any]] = {}
        for pid, sigs in grouped.items():
            out[pid] = calculate_consensus(sigs)
        return out
