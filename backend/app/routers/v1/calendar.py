"""Airdrop Calendar Router (空投里程碑与倒计时日历路由).

GET /api/v1/calendar/events
GET /api/v1/calendar/export.ics
"""

from typing import Any

import structlog
from fastapi import APIRouter, Query, Response

from app.services.airdrop_calendar import (
    generate_icalendar_stream,
    get_calendar_events,
)
from app.utils.data_quality import mark_real, mark_simulated

_CALENDAR_SIMULATED_NOTE = (
    "部分或全部里程碑日期为滚动演示数据（当前日期 + 固定偏移）；可通过 ?real_only=true 仅拉取数据库真实登记节点。"
)
_CALENDAR_REAL_NOTE = "全部里程碑节点均来自项目数据库已登记的真实未来截止时间。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/events", summary="获取所有空投关键里程碑与倒计时列表")
def list_calendar_events(
    real_only: bool = Query(default=False, description="为 true 时仅返回数据库已登记真实日期节点，不注入滚动演示数据"),
) -> dict[str, Any]:
    """返回聚合排序后的空投里程碑事件（按是否含滚动演示节点动态标注 real / simulated）."""
    events = get_calendar_events(include_demo_fallback=not real_only)
    real_count = sum(1 for ev in events if not ev.get("is_simulated", False))
    simulated_count = len(events) - real_count
    payload = {
        "ok": True,
        "data": {
            "events": events,
            "total": len(events),
            "real_count": real_count,
            "simulated_count": simulated_count,
        },
    }
    if real_only or (events and simulated_count == 0):
        return mark_real(payload, note=_CALENDAR_REAL_NOTE)
    return mark_simulated(payload, note=_CALENDAR_SIMULATED_NOTE)


@router.get("/export.ics", summary="导出并订阅标准 iCalendar (.ics) 日历文件")
def export_ical_file(
    real_only: bool = Query(default=False, description="为 true 时仅导出真实已登记里程碑节点"),
) -> Response:
    """生成标准 .ics 日历文件流，供导入 Google Calendar 或 Apple 日历."""
    events = get_calendar_events(include_demo_fallback=not real_only)
    ics_content = generate_icalendar_stream(events)

    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="airdrop_milestones.ics"',
        },
    )
