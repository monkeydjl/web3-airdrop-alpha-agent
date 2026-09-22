"""Unit tests for Airdrop Milestone Calendar Service and API."""

from app.services.airdrop_calendar import (
    generate_icalendar_stream,
    get_calendar_events,
)


def test_get_calendar_events():
    """验证获取事件列表包含倒计时与紧急度字段."""
    events = get_calendar_events()
    assert isinstance(events, list)
    assert len(events) > 0

    first = events[0]
    assert "project_id" in first
    assert "event_type" in first
    assert "deadline_iso" in first
    assert "hours_remaining" in first
    assert "urgency" in first
    assert first["urgency"] in ("urgent", "soon", "normal")


def test_generate_icalendar_stream():
    """验证生成的 .ics 文本符合 RFC 5545 格式规范."""
    events = get_calendar_events()
    ics = generate_icalendar_stream(events)

    assert "BEGIN:VCALENDAR" in ics
    assert "VERSION:2.0" in ics
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:" in ics
    assert "END:VCALENDAR" in ics
