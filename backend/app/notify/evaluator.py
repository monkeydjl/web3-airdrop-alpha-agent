"""决策推送事件评估器（ACTION_LOOP_DESIGN.md §2.3）。

评估器只读数据库的既成事实（评分历史 / 今日新项目 / 观察列表的新采集行），
产出「值得推送的事件」列表。它是纯查询 + 纯判断：不写库、不发网络请求、
不感知通道 —— 同一事件由 cron 与 pipeline 收尾钩子重复产出是**预期的**，
去重交给 notify_log 的 `(event_key, channel)` 唯一约束（service 层）。

事件类型与去重键（见设计文档 §2.3 的表）：

| event_type       | event_key                                |
|------------------|------------------------------------------|
| daily_digest     | digest:{YYYY-MM-DD}                      |
| score_crossing   | cross:{project_id}:{up_farm|down_watch}:{date} |
| new_farm         | new_farm:{project_id}                    |
| watchlist_signal | signal:{project_id}:{raw_id}             |
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# 跨线阈值与 scorer.LABEL_THRESHOLDS（65 FARM / 50 WATCH）对齐。
# 不直接 import LABEL_THRESHOLDS：那是「打分用」的有序表，这里要的是
# 两个语义明确的常量；scorer 改阈值时两处会由测试钉住同步
# （test_notify.py 与 test_scorer 的阈值断言各管各的）。
FARM_THRESHOLD = 65
WATCH_FLOOR = 50

# Telegram 单条消息上限 4096 字符，标题 + 空行 + 正文要一起塞进去，
# 正文留出标题的余量。截断是产品语义（摘要本就是节选），不是丢数据。
MAX_BODY_CHARS = 3000

# 观察列表信号事件只挑「强信号」原始行：raw_data 带这些 flag 的才算值得吵用户。
_STRONG_SIGNAL_FLAGS = ("recent_funding", "has_testnet")


@dataclass(frozen=True)
class NotifyEvent:
    """一条待推送事件。event_key 承担跨运行去重，必须稳定可复算。"""

    event_type: str
    event_key: str
    title: str
    body: str


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _window_start(now: datetime) -> str:
    """「今日」窗口起点（UTC 零点），格式兼容 SQLite 存的墙钟字符串。"""
    return datetime.combine(now.date(), time.min, tzinfo=UTC).strftime("%Y-%m-%d %H:%M:%S")


def _day_tag(now: datetime) -> str:
    return now.strftime("%Y-%m-%d")


def _row_value(row: Any, key: str, default: Any = None) -> Any:
    """兼容 sqlite3.Row 与 psycopg dict_row（同 notifications.py 的写法）。"""
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def detect_crossing(*, previous_score: int | None, current_score: int | None) -> str | None:
    """判断分数跨线方向。

    - ``up_farm``：此前 < 65 且现在 >= 65（首次进入 FARM 档）
    - ``down_watch``：此前 >= 50 且现在 < 50（跌出 WATCH 档）
    - 其余（含任一侧为 None）返回 None —— 数据不全不猜。

    中间地带（50-65 区间内的上浮下沉、FARM 档内的回落但不破 50）**刻意
    不报**：推送的价值在于「档位变化」，分数抖动不该消耗用户的注意力。
    """
    if previous_score is None or current_score is None:
        return None
    if previous_score < FARM_THRESHOLD <= current_score:
        return "up_farm"
    if previous_score >= WATCH_FLOOR > current_score:
        return "down_watch"
    return None


def _project_ref(pid: str, name: str | None) -> str:
    return f"{(name or '').strip() or pid} ({pid})"


def _new_projects_today(conn: Any, window_start: str) -> list[dict[str, Any]]:
    cursor = conn.execute(
        """
        SELECT id, name, score, label
        FROM projects
        WHERE created_at >= ? AND label IN ('FARM', 'WATCH')
        ORDER BY score DESC
        """,
        (window_start,),
    )
    return [dict(r) for r in cursor.fetchall()]


def _crossings_today(conn: Any, window_start: str) -> list[dict[str, Any]]:
    """今日有评分写入的项目 → 各取最新两条历史，交给 detect_crossing。"""
    cursor = conn.execute(
        """
        SELECT h.project_id, h.score, p.name AS project_name
        FROM project_history h
        LEFT JOIN projects p ON p.id = h.project_id
        WHERE h.project_id IN (
            SELECT DISTINCT project_id FROM project_history
            WHERE created_at >= ?
        )
        ORDER BY h.project_id, h.created_at DESC, h.id DESC
        """,
        (window_start,),
    )
    by_project: dict[str, list[int | None]] = {}
    names: dict[str, str | None] = {}
    for row in cursor.fetchall():
        pid = str(_row_value(row, "project_id") or "")
        if not pid:
            continue
        if pid not in by_project:
            by_project[pid] = []
            names[pid] = _row_value(row, "project_name")
        if len(by_project[pid]) < 2:
            by_project[pid].append(_row_value(row, "score"))
    out: list[dict[str, Any]] = []
    for pid, scores in by_project.items():
        previous = scores[1] if len(scores) > 1 else None
        current = scores[0] if scores else None
        direction = detect_crossing(previous_score=previous, current_score=current)
        if direction:
            out.append(
                {
                    "project_id": pid,
                    "project_name": names.get(pid),
                    "direction": direction,
                    "previous_score": previous,
                    "current_score": current,
                }
            )
    return out


def _watchlist_signals_today(conn: Any, window_start: str) -> list[dict[str, Any]]:
    """观察列表项目的今日新采集行（只挑强信号 flag 的原始行）。"""
    cursor = conn.execute(
        """
        SELECT r.raw_id, r.project_id, r.source_id, r.raw_data, r.discovered_at
        FROM raw_projects r
        WHERE r.project_id IN (SELECT DISTINCT project_id FROM watchlist)
          AND r.discovered_at >= ?
        ORDER BY r.discovered_at DESC
        """,
        (window_start,),
    )
    out: list[dict[str, Any]] = []
    for row in cursor.fetchall():
        raw_data: dict[str, Any] = {}
        raw_text = _row_value(row, "raw_data")
        if raw_text:
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    raw_data = parsed
            except (ValueError, TypeError):
                # 坏行只影响这一条的判断，隔离由分析队列负责，这里直接跳过
                continue
        flags = [f for f in _STRONG_SIGNAL_FLAGS if raw_data.get(f)]
        if not flags:
            continue
        out.append(
            {
                "raw_id": str(_row_value(row, "raw_id") or ""),
                "project_id": str(_row_value(row, "project_id") or ""),
                "project_name": raw_data.get("name") or "",
                "source_id": str(_row_value(row, "source_id") or ""),
                "flags": flags,
            }
        )
    return out


def _digest_event(new_projects: list[dict[str, Any]], now: datetime) -> NotifyEvent | None:
    """每日摘要：今日新增 FARM/WATCH 计数 + 最高分项目。没有新项目就不发。"""
    if not new_projects:
        return None
    farms = [p for p in new_projects if p.get("label") == "FARM"]
    watches = [p for p in new_projects if p.get("label") == "WATCH"]
    lines = [
        f"今日新增 FARM {len(farms)} 个 / WATCH {len(watches)} 个。",
    ]
    top = new_projects[0]
    lines.append(
        f"最高分：{_project_ref(str(top.get('id') or ''), top.get('name'))} "
        f"score={top.get('score')} label={top.get('label')}"
    )
    for p in farms[:5]:
        lines.append(f"- [FARM] {_project_ref(str(p.get('id') or ''), p.get('name'))} score={p.get('score')}")
    if len(farms) > 5:
        lines.append(f"- …另有 {len(farms) - 5} 个 FARM 略")
    return NotifyEvent(
        event_type="daily_digest",
        event_key=f"digest:{_day_tag(now)}",
        title="空投雷达每日摘要",
        body="\n".join(lines)[:MAX_BODY_CHARS],
    )


def evaluate_events(
    conn: Any,
    *,
    now: datetime | None = None,
    include_digest: bool = True,
) -> list[NotifyEvent]:
    """评估当前库里值得推送的事件。

    Args:
        conn: 数据库连接（只读查询）。
        now: 「今日」基准，默认当前 UTC 时间（测试注入用）。
        include_digest: pipeline 收尾钩子传 False（摘要是 cron 的职责，
            每轮 run 都发一条摘要等于刷屏）。
    """
    now = now or _utc_now()
    window = _window_start(now)
    events: list[NotifyEvent] = []

    if include_digest:
        new_projects = _new_projects_today(conn, window)
        digest = _digest_event(new_projects, now)
        if digest:
            events.append(digest)

    for c in _crossings_today(conn, window):
        direction = c["direction"]
        if direction == "up_farm":
            title = f"跨入 FARM：score {c['previous_score']} → {c['current_score']}"
        else:
            title = f"跌出 WATCH：score {c['previous_score']} → {c['current_score']}"
        events.append(
            NotifyEvent(
                event_type="score_crossing",
                event_key=f"cross:{c['project_id']}:{direction}:{_day_tag(now)}",
                title=title,
                body=f"{_project_ref(str(c['project_id']), c['project_name'])}",
            )
        )

    # 新 FARM 不受 include_digest 门控：摘要是 cron 的职责，但「出现新 FARM」
    # 是实时事件，pipeline 落库钩子就要评估（event_key 是项目级、只发一次）。
    for p in _new_projects_today(conn, window):
        if p.get("label") == "FARM":
            pid = str(p.get("id") or "")
            events.append(
                NotifyEvent(
                    event_type="new_farm",
                    event_key=f"new_farm:{pid}",
                    title=f"新 FARM 项目：score={p.get('score')}",
                    body=_project_ref(pid, p.get("name")),
                )
            )

    for s in _watchlist_signals_today(conn, window):
        events.append(
            NotifyEvent(
                event_type="watchlist_signal",
                event_key=f"signal:{s['project_id']}:{s['raw_id']}",
                title=f"观察列表新信号（{s['source_id']}）：{'、'.join(s['flags'])}",
                body=_project_ref(s["project_id"], s["project_name"]),
            )
        )

    logger.info(
        "notify.events_evaluated",
        total=len(events),
        digest=include_digest,
    )
    return events
