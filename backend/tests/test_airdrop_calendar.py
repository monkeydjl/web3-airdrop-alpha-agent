"""Unit & API tests for Airdrop Milestone Calendar Service (real deadlines + fallback)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import connection_scope, init_db
from app.main import create_app
from app.services.airdrop_calendar import (
    generate_icalendar_stream,
    get_calendar_events,
)


def test_get_calendar_events() -> None:
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


def test_generate_icalendar_stream() -> None:
    """验证生成的 .ics 文本符合 RFC 5545 格式规范."""
    events = get_calendar_events()
    ics = generate_icalendar_stream(events)

    assert "BEGIN:VCALENDAR" in ics
    assert "VERSION:2.0" in ics
    assert "BEGIN:VEVENT" in ics
    assert "SUMMARY:" in ics
    assert "END:VCALENDAR" in ics


def test_calendar_extracts_real_project_deadlines_and_marks_real_quality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_file = tmp_path / "calendar_real.db"
    monkeypatch.setattr(settings, "db_path", str(db_file))
    monkeypatch.setattr(settings, "db_backend", "sqlite")
    init_db()

    future_dt = (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=3)).isoformat()
    meta_json = json.dumps(
        {
            "tge_date": future_dt,
            "milestones": [
                {
                    "type": "snapshot",
                    "title": "RealProject 第一季积分锁定快照",
                    "deadline_iso": (datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=1)).isoformat(),
                }
            ],
        },
        ensure_ascii=False,
    )
    with connection_scope() as conn:
        conn.execute(
            """
            INSERT INTO projects (id, name, sector, stage, score, label, source, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("real-proj-1", "RealProject", "L2", "testnet", 88, "FARM", "defillama", meta_json),
        )
        conn.commit()

    app = create_app()
    with TestClient(app) as client:
        resp_real = client.get("/api/v1/calendar/events", params={"real_only": "true"})
        assert resp_real.status_code == 200
        body = resp_real.json()
        assert body["data_quality"]["quality"] == "real"
        assert body["data"]["real_count"] == 2
        assert body["data"]["simulated_count"] == 0
        assert all(ev["is_simulated"] is False for ev in body["data"]["events"])
