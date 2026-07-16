"""Tests for the feedback and events endpoints."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_feedback_tables():
    """每次测试前清理 feedback/events 表。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.commit()
    yield


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def feedback_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    monkeypatch.setattr(settings, "enable_events_tracking", True)


class TestFeedbackEndpoints:
    def test_feedback_disabled_when_flag_off(self, client, monkeypatch) -> None:
        """显式关闭反馈系统时拒绝写入。"""
        monkeypatch.setattr(settings, "enable_feedback_system", False)
        response = client.post(
            "/api/v1/feedback",
            json={
                "project_id": "layerx-001",
                "signal": "useful",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "FEEDBACK_DISABLED"

    def test_submit_feedback(self, client, feedback_enabled) -> None:
        response = client.post(
            "/api/v1/feedback",
            json={
                "project_id": "layerx-001",
                "user_id": "anon-123",
                "signal": "useful",
                "note": "Looks promising",
                "outcome": "airdropped",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["project_id"] == "layerx-001"
        assert data["signal"] == "useful"
        assert "feedback_id" in data

    def test_get_feedback(self, client, feedback_enabled) -> None:
        client.post(
            "/api/v1/feedback",
            json={
                "project_id": "layerx-001",
                "signal": "useful",
            },
        )
        client.post(
            "/api/v1/feedback",
            json={
                "project_id": "layerx-001",
                "signal": "useless",
            },
        )

        response = client.get("/api/v1/feedback/layerx-001")
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["count"] == 2
        assert data["signals"]["useful"] == 1
        assert data["signals"]["useless"] == 1


class TestEventsEndpoints:
    def test_events_disabled_by_default(self, client) -> None:
        response = client.post(
            "/api/v1/events",
            json={
                "project_id": "layerx-001",
                "event_type": "expand",
            },
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "EVENTS_DISABLED"

    def test_submit_event(self, client, feedback_enabled) -> None:
        response = client.post(
            "/api/v1/events",
            json={
                "project_id": "layerx-001",
                "user_id": "anon-123",
                "event_type": "expand",
                "detail": '{"duration_ms": 1200}',
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["event_type"] == "expand"
        assert "event_id" in data
