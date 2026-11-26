"""Airdrop Milestone & TGE Countdown Calendar Service (空投里程碑、快照与 TGE 倒计时日历).

优先从数据库 `projects.meta`（`milestones` / `signals` / 显式截止日期字段）抽取经核实的真实
ISO 时间节点（`is_simulated: False`）；仅在真实未来节点不足且允许演示回退时补充滚动示例节点，
支持标准 iCalendar (.ics) 日历订阅与导出。
"""

from __future__ import annotations

import datetime
import json
from typing import Any

import structlog

from app.db import connection_scope, dict_from_row

logger = structlog.get_logger(__name__)

_EVENT_TYPE_ZH: dict[str, str] = {
    "tge": "TGE 发币上线",
    "snapshot": "快照截止",
    "claim": "空投认领",
    "testnet": "测试网截止",
}

_META_DATE_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("tge_date", "tge", "代币 TGE 里程碑"),
    ("tge_deadline", "tge", "代币 TGE 截止"),
    ("snapshot_date", "snapshot", "空投交互快照节点"),
    ("snapshot_deadline", "snapshot", "空投快照截止"),
    ("claim_deadline", "claim", "空投代币认领截止"),
    ("testnet_deadline", "testnet", "激励测试网任务截止"),
    ("deadline_iso", "snapshot", "项目关键截止节点"),
)


def _parse_future_iso(raw_val: Any, now: datetime.datetime) -> datetime.datetime | None:
    if not isinstance(raw_val, str) or not raw_val.strip():
        return None
    text = raw_val.strip()
    if len(text) == 10 and text[4] == "-" and text[7] == "-":
        text = f"{text}T00:00:00+00:00"
    elif text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.UTC)
    if dt <= now:
        return None
    return dt.astimezone(datetime.UTC)


def _build_event(
    *,
    event_id: str,
    project_id: str,
    project_name: str,
    sector: Any,
    label: Any,
    score: Any,
    event_type: str,
    title: str,
    description: str,
    event_time: datetime.datetime,
    now: datetime.datetime,
    is_simulated: bool,
) -> dict[str, Any]:
    hours_left = max(0, int((event_time - now).total_seconds() // 3600))
    days_left = round(hours_left / 24, 1)
    urgency = "urgent" if hours_left <= 48 else ("soon" if hours_left <= 168 else "normal")
    return {
        "id": event_id,
        "project_id": project_id,
        "project_name": project_name,
        "sector": sector,
        "label": label,
        "score": score,
        "event_type": event_type,
        "event_type_zh": _EVENT_TYPE_ZH.get(event_type, "里程碑"),
        "title": title,
        "description": description,
        "deadline_iso": event_time.isoformat(),
        "hours_remaining": hours_left,
        "days_remaining": days_left,
        "urgency": urgency,
        "is_simulated": is_simulated,
    }


def _extract_real_project_milestones(record: dict[str, Any], now: datetime.datetime) -> list[dict[str, Any]]:
    raw_meta = record.get("meta")
    meta: dict[str, Any] = {}
    if isinstance(raw_meta, dict):
        meta = raw_meta
    elif isinstance(raw_meta, str) and raw_meta.strip():
        try:
            parsed = json.loads(raw_meta)
            if isinstance(parsed, dict):
                meta = parsed
        except Exception:
            meta = {}

    if not meta:
        return []

    out: list[dict[str, Any]] = []
    pid = str(record.get("id") or "")
    pname = str(record.get("name") or pid)
    seen_keys: set[tuple[str, str]] = set()

    # 1. 结构化 meta.milestones 列表
    milestones = meta.get("milestones")
    if isinstance(milestones, list):
        for idx, item in enumerate(milestones):
            if not isinstance(item, dict):
                continue
            dt = _parse_future_iso(item.get("deadline_iso") or item.get("date"), now)
            if dt is None:
                continue
            ev_type = str(item.get("type") or "snapshot").lower().strip()
            key = (ev_type, dt.date().isoformat())
            if key in seen_keys:
                continue
            seen_keys.add(key)
            out.append(
                _build_event(
                    event_id=f"{pid}-real-{ev_type}-{idx}",
                    project_id=pid,
                    project_name=pname,
                    sector=record.get("sector"),
                    label=record.get("label"),
                    score=record.get("score"),
                    event_type=ev_type,
                    title=str(item.get("title") or f"{pname} {_EVENT_TYPE_ZH.get(ev_type, '里程碑')}"),
                    description=str(item.get("description") or f"{pname} 已登记里程碑节点"),
                    event_time=dt,
                    now=now,
                    is_simulated=False,
                )
            )

    # 2. 顶层 meta 与 meta.signals 中的显式日期字段
    signals = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    for field_name, ev_type, suffix_zh in _META_DATE_FIELDS:
        raw_date = meta.get(field_name) or (signals.get(field_name) if isinstance(signals, dict) else None)
        dt = _parse_future_iso(raw_date, now)
        if dt is None:
            continue
        key = (ev_type, dt.date().isoformat())
        if key in seen_keys:
            continue
        seen_keys.add(key)
        out.append(
            _build_event(
                event_id=f"{pid}-real-{field_name}",
                project_id=pid,
                project_name=pname,
                sector=record.get("sector"),
                label=record.get("label"),
                score=record.get("score"),
                event_type=ev_type,
                title=f"{pname} {suffix_zh}",
                description=f"来自项目元数据字段 {field_name} 的真实截止时间",
                event_time=dt,
                now=now,
                is_simulated=False,
            )
        )

    return out


def get_calendar_events(*, include_demo_fallback: bool = True) -> list[dict[str, Any]]:
    """聚合项目关键里程碑时间节点（优先真实 ISO 日期，按需补充滚动演示节点）."""
    events: list[dict[str, Any]] = []

    with connection_scope() as conn:
        rows = conn.execute(
            """
            SELECT id, name, sector, stage, score, label, meta
            FROM projects
            WHERE (source != 'historical_backfill' OR source IS NULL) AND hidden_reason IS NULL
            """
        ).fetchall()

        now = datetime.datetime.now(datetime.UTC)
        records = [dict_from_row(row) for row in rows]

        for record in records:
            events.extend(_extract_real_project_milestones(record, now))

        if not include_demo_fallback or len(events) >= 4:
            events.sort(key=lambda x: x["hours_remaining"])
            return events

        curated_milestones: dict[str, list[dict[str, Any]]] = {
            "berachain": [
                {
                    "type": "tge",
                    "title": "Berachain 主网启动与代币 TGE",
                    "days_offset": 14,
                    "desc": "Boyco 流动性预热结束，主网正式上线及空投资格激活",
                },
                {
                    "type": "snapshot",
                    "title": "Berachain 测试网交互最终快照",
                    "days_offset": 2,
                    "desc": "Bartio 测试网验证者与 DApp 交互地址最终汇总锁定",
                },
            ],
            "story": [
                {
                    "type": "testnet",
                    "title": "Story Protocol Odyssey 测试网第二期结算",
                    "days_offset": 5,
                    "desc": "知识产权 IP 铸造与许可协议交互积分最终快照",
                }
            ],
            "symbiotic": [
                {
                    "type": "snapshot",
                    "title": "Symbiotic 第一季质押沉淀快照",
                    "days_offset": 8,
                    "desc": "LRT/mETH 质押池加权时长与网络安全共享积分核算",
                }
            ],
            "monad": [
                {
                    "type": "testnet",
                    "title": "Monad 公共测试网 Devnet 迁移节点",
                    "days_offset": 20,
                    "desc": "并行 EVM 社区压力测试任务与生态早期凭证领取",
                }
            ],
        }

        existing_project_ids = {str(ev["project_id"]).lower() for ev in events}
        matched_names: set[str] = set()

        for record in records:
            pid = str(record.get("id") or "").lower()
            name = str(record.get("name") or "").lower()
            if pid in existing_project_ids:
                continue

            for key, m_list in curated_milestones.items():
                if (key in pid or key in name) and key not in matched_names:
                    matched_names.add(key)
                    for m in m_list:
                        event_time = now + datetime.timedelta(days=m["days_offset"])
                        events.append(
                            _build_event(
                                event_id=f"{pid}-{m['type']}-{m['days_offset']}",
                                project_id=str(record["id"]),
                                project_name=str(record["name"]),
                                sector=record.get("sector"),
                                label=record.get("label"),
                                score=record.get("score"),
                                event_type=m["type"],
                                title=m["title"],
                                description=m["desc"],
                                event_time=event_time,
                                now=now,
                                is_simulated=True,
                            )
                        )

        if len(events) < 4:
            fallback_events: list[dict[str, Any]] = [
                {
                    "project_id": "linea",
                    "project_name": "Linea",
                    "sector": "L2",
                    "label": "FARM",
                    "score": 85,
                    "event_type": "snapshot",
                    "title": "Linea Voyage LXP 最终女巫审查与清洗公示",
                    "description": "反女巫最终申诉截止，公示通过名单并锁定 TGE 权重大表",
                    "days_offset": 1.5,
                },
                {
                    "project_id": "fuel",
                    "project_name": "Fuel Network",
                    "sector": "Execution Layer",
                    "label": "FARM",
                    "score": 82,
                    "event_type": "tge",
                    "title": "Fuel 主网积分第二季分配上线",
                    "description": "Fuel Ignition 沉淀资产解锁与第一期代币空投入口开放",
                    "days_offset": 6,
                },
            ]
            for fe in fallback_events:
                event_time = now + datetime.timedelta(days=fe["days_offset"])
                events.append(
                    _build_event(
                        event_id=f"{fe['project_id']}-{fe['event_type']}",
                        project_id=fe["project_id"],
                        project_name=fe["project_name"],
                        sector=fe["sector"],
                        label=fe["label"],
                        score=fe["score"],
                        event_type=fe["event_type"],
                        title=fe["title"],
                        description=fe["description"],
                        event_time=event_time,
                        now=now,
                        is_simulated=True,
                    )
                )

        events.sort(key=lambda x: x["hours_remaining"])

    return events


def generate_icalendar_stream(events: list[dict[str, Any]]) -> str:
    """将里程碑事件生成为标准的 iCalendar (RFC 5545) 纯文本格式."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Web3 Airdrop Alpha Agent//Airdrop Calendar//CN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "X-WR-CALNAME:Web3 空投关键里程碑与快照日历",
        "X-WR-TIMEZONE:UTC",
    ]

    for ev in events:
        try:
            dt = datetime.datetime.fromisoformat(ev["deadline_iso"].replace("Z", "+00:00"))
            dt_str = dt.strftime("%Y%m%dT%H%M%SZ")
            end_dt_str = (dt + datetime.timedelta(hours=1)).strftime("%Y%m%dT%H%M%SZ")
            uid = f"{ev['id']}@airdrop-alpha-agent"

            lines.extend(
                [
                    "BEGIN:VEVENT",
                    f"UID:{uid}",
                    f"DTSTAMP:{dt_str}",
                    f"DTSTART:{dt_str}",
                    f"DTEND:{end_dt_str}",
                    f"SUMMARY:[{ev['event_type_zh']}] {ev['title']}",
                    f"DESCRIPTION:{ev['description']} (项目: {ev['project_name']} | 评分: {ev['score']})",
                    "STATUS:CONFIRMED",
                    "BEGIN:VALARM",
                    "TRIGGER:-PT24H",
                    "ACTION:DISPLAY",
                    f"DESCRIPTION:空投截止倒计时提醒: {ev['title']}",
                    "END:VALARM",
                    "END:VEVENT",
                ]
            )
        except Exception as exc:
            logger.debug("airdrop_calendar.ics_event_skipped", error=repr(exc))
            continue

    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
