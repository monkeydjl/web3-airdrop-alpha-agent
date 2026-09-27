"""Airdrop Calendar Router (空投里程碑与倒计时日历路由).

GET /api/v1/calendar/events
GET /api/v1/calendar/export.ics
"""

from typing import Any

import structlog
from fastapi import APIRouter, Response

from app.services.airdrop_calendar import (
    generate_icalendar_stream,
    get_calendar_events,
)
from app.utils.data_quality import mark_simulated

# 日历里程碑的日期为「now + N 天」滚动生成（CURATED_MILESTONES / fallback），非真实时间线
_CALENDAR_NOTE = (
    "里程碑日期为演示数据：由「当前日期 + 固定偏移」滚动生成以维持倒计时展示，并非经核实的真实快照/TGE 时间。"
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/calendar", tags=["calendar"])


@router.get("/events", summary="获取所有空投关键里程碑与倒计时列表")
def list_calendar_events() -> dict[str, Any]:
    """返回聚合排序后的空投里程碑事件（打模拟标记，见 _CALENDAR_NOTE）."""
    events = get_calendar_events()
    return mark_simulated(
        {
            "ok": True,
            "data": {
                "events": events,
                "total": len(events),
            },
        },
        note=_CALENDAR_NOTE,
    )


@router.get("/export.ics", summary="导出并订阅标准 iCalendar (.ics) 日历文件")
def export_ical_file() -> Response:
    """生成标准 .ics 日历文件流，供导入 Google Calendar 或 Apple 日历."""
    events = get_calendar_events()
    ics_content = generate_icalendar_stream(events)

    return Response(
        content=ics_content,
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="airdrop_milestones.ics"',
        },
    )
