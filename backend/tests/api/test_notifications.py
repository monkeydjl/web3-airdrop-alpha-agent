"""Tests for the notifications aggregation endpoint."""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def client(tmp_path, monkeypatch):
    """使用临时数据库创建隔离的 TestClient。"""
    db_path = tmp_path / "notifications_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    app = create_app()
    return TestClient(app)


class TestNotifications:
    def test_notifications_empty(self, client) -> None:
        """空库时返回结构完整且无通知。"""
        response = client.get("/api/v1/notifications")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        data = body["data"]
        assert set(data) == {"unread_count", "items"}
        assert data["unread_count"] == 0
        assert data["items"] == []

    def test_new_farm_project_notification(self, client) -> None:
        """今日新 FARM 项目应生成 new_project 通知。"""
        projects = [
            {
                "name": "Notif L2 Alpha",
                "sector": "L2",
                "stage": "testnet",
                "has_testnet": True,
                "has_points_program": True,
                "no_token_yet": True,
                "recent_funding": True,
            },
        ]
        run_res = client.post("/api/v1/run", json={"projects": projects, "enable_llm": False})
        assert run_res.status_code == 200

        response = client.get("/api/v1/notifications")
        body = response.json()
        data = body["data"]
        new_projects = [it for it in data["items"] if it["type"] == "new_project"]
        assert new_projects, "今日新建高分项目应生成 new_project 通知"
        assert new_projects[0]["title"].startswith("今日新进")
        assert new_projects[0]["link"]["href"].startswith("/project/")

    def test_collector_failure_notification(self, client) -> None:
        """手动插入一条失败的采集日志应生成 collector 告警通知。"""
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO collection_logs (log_id, source_id, started_at, finished_at, "
                "items_collected, items_new, items_duplicate, status, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "log-test-1",
                    "defillama",
                    _now(),
                    _now(),
                    0,
                    0,
                    0,
                    "failed",
                    "401 unauthorized",
                ),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/api/v1/notifications")
        body = response.json()
        collectors = [it for it in body["data"]["items"] if it["type"] == "collector"]
        assert collectors, "失败采集日志应生成 collector 告警"
        assert "采集器失败" in collectors[0]["title"]
        assert collectors[0]["link"]["href"] == "/ops"
