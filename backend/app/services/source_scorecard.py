"""采集源评分卡：用真实采集结果衡量每个源值不值得继续跑。

数据全部来自 ``raw_projects`` 与 ``data_sources``，不做任何估算：
- 产量、分析率、隔离率、平均发现分
- 最近一次同步时间与新鲜度
- 基于以上事实给出 verdict 与处理建议
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from app.db import DbConnection

# 与 anomaly_detection 的 source stale 阈值保持一致。
STALE_HOURS = 72.0
DEFAULT_SIGNAL_THRESHOLD = 0.30
NOISY_QUARANTINE_RATE = 0.40
LOW_SIGNAL_AVG_SCORE = 0.20
LOW_SIGNAL_MIN_ROWS = 20


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _verdict(
    *,
    total_raw: int,
    analyzed: int,
    quarantined: int,
    avg_score: float | None,
    freshness_hours: float | None,
    sync_status: str | None,
) -> tuple[str, str]:
    quarantine_rate = quarantined / total_raw if total_raw else 0.0

    if sync_status == "error":
        return "failing", "最近同步失败，先排查凭据或网络，再决定是否保留"
    if total_raw == 0:
        if freshness_hours is not None and freshness_hours > STALE_HOURS:
            return "stale", f"超过 {int(STALE_HOURS)} 小时未同步，检查调度与凭据"
        if sync_status == "success":
            return "no_data", "同步成功但没有产出，检查采集解析或筛选规则"
        return "idle", "尚未采集到数据"
    if quarantine_rate >= NOISY_QUARANTINE_RATE:
        return "noisy", "隔离率过高，建议降权或关闭，避免污染发现队列"
    if total_raw >= LOW_SIGNAL_MIN_ROWS and (avg_score or 0.0) < LOW_SIGNAL_AVG_SCORE:
        return "low_signal", "平均发现分偏低，建议降权或关闭"
    if freshness_hours is not None and freshness_hours > STALE_HOURS:
        return "stale", f"超过 {int(STALE_HOURS)} 小时未同步，检查调度与凭据"
    if analyzed == 0:
        return "idle", "有原始记录但未进入分析，检查发现阈值与队列"
    return "healthy", "产出稳定，可保持当前调度"


def fetch_source_scorecards(
    conn: DbConnection,
    source_ids: Iterable[str],
    *,
    signal_threshold: float = DEFAULT_SIGNAL_THRESHOLD,
    now: datetime | None = None,
) -> dict[str, dict[str, Any]]:
    """批量返回 {source_id: scorecard}，未知源返回空指标 + idle。"""
    ids = list(dict.fromkeys(str(source_id) for source_id in source_ids))
    if not ids:
        return {}

    placeholders = ",".join("?" for _ in ids)
    params = tuple(ids)

    rows = conn.execute(
        f"""
        SELECT
            source_id,
            COUNT(*) AS total_raw,
            SUM(CASE WHEN processed = 1 THEN 1 ELSE 0 END) AS analyzed,
            SUM(CASE WHEN processed = 0 THEN 1 ELSE 0 END) AS pending,
            SUM(CASE WHEN quarantined = 1 THEN 1 ELSE 0 END) AS quarantined,
            SUM(CASE WHEN discovery_score >= ? THEN 1 ELSE 0 END) AS high_signal,
            AVG(CASE WHEN discovery_score IS NOT NULL THEN discovery_score END) AS avg_score,
            MAX(discovered_at) AS last_discovered_at
        FROM raw_projects
        WHERE source_id IN ({placeholders})
        GROUP BY source_id
        """,  # noqa: S608 — IN 占位符按数量生成，取值全部走绑定参数
        (signal_threshold, *params),
    ).fetchall()
    metrics = {str(row["source_id"]): row for row in rows}

    source_rows = conn.execute(
        f"""
        SELECT source_id, sync_status, last_sync
        FROM data_sources
        WHERE source_id IN ({placeholders})
        """,  # noqa: S608 — 同上，仅占位符动态生成
        params,
    ).fetchall()
    statuses = {str(row["source_id"]): row for row in source_rows}

    current = now or datetime.now(UTC)
    cards: dict[str, dict[str, Any]] = {}

    for source_id in ids:
        row = metrics.get(source_id)
        status = statuses.get(source_id)

        total_raw = int(row["total_raw"] or 0) if row is not None else 0
        analyzed = int(row["analyzed"] or 0) if row is not None else 0
        pending = int(row["pending"] or 0) if row is not None else 0
        quarantined = int(row["quarantined"] or 0) if row is not None else 0
        high_signal = int(row["high_signal"] or 0) if row is not None else 0
        avg_score = round(float(row["avg_score"]), 4) if row is not None and row["avg_score"] is not None else None

        last_sync = _parse_dt(status["last_sync"]) if status is not None else None
        freshness_hours = round((current - last_sync).total_seconds() / 3600, 2) if last_sync is not None else None
        sync_status = str(status["sync_status"]) if status is not None and status["sync_status"] else None

        verdict, recommendation = _verdict(
            total_raw=total_raw,
            analyzed=analyzed,
            quarantined=quarantined,
            avg_score=avg_score,
            freshness_hours=freshness_hours,
            sync_status=sync_status,
        )

        cards[source_id] = {
            "total_raw": total_raw,
            "analyzed": analyzed,
            "pending": pending,
            "quarantined": quarantined,
            "high_signal": high_signal,
            "avg_discovery_score": avg_score,
            "analysis_rate": round(analyzed / total_raw, 4) if total_raw else 0.0,
            "quarantine_rate": round(quarantined / total_raw, 4) if total_raw else 0.0,
            "last_discovered_at": (
                str(row["last_discovered_at"]) if row is not None and row["last_discovered_at"] else None
            ),
            "last_sync": status["last_sync"] if status is not None else None,
            "freshness_hours": freshness_hours,
            "verdict": verdict,
            "recommendation": recommendation,
        }

    return cards
