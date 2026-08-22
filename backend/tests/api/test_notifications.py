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
        assert new_projects[0]["read"] is False

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

    def test_score_change_notification(self, client) -> None:
        """同一项目两条不同 score 的 history 应生成 score 通知。"""
        # 先创建项目
        run_res = client.post(
            "/api/v1/run",
            json={
                "projects": [
                    {
                        "name": "Score Shift",
                        "sector": "DeFi",
                        "stage": "testnet",
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "recent_funding": True,
                    }
                ],
                "enable_llm": False,
            },
        )
        assert run_res.status_code == 200
        projects = client.get("/api/v1/projects?page_size=10").json()["data"]["projects"]
        assert projects
        pid = projects[0]["id"]
        name = projects[0]["name"]

        # 再插入一条更高分的历史（模拟 re-score 变化）
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO project_history "
                "(project_id, run_id, score, label, stage, weight_version, snapshot, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    pid,
                    "manual-rescore-1",
                    90,
                    "FARM",
                    "testnet",
                    "score-v1.4",
                    "{}",
                    _now(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        response = client.get("/api/v1/notifications")
        body = response.json()
        scores = [it for it in body["data"]["items"] if it["type"] == "score"]
        assert scores, "评分变化应生成 score 通知"
        assert name in scores[0]["title"]
        assert scores[0]["project_id"] == pid

    def test_mark_read_persists(self, client) -> None:
        """标记已读后再次拉取应为 read=true，unread_count 下降。"""
        run_res = client.post(
            "/api/v1/run",
            json={
                "projects": [
                    {
                        "name": "Read Me",
                        "sector": "L2",
                        "stage": "testnet",
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "recent_funding": True,
                    }
                ],
                "enable_llm": False,
            },
        )
        assert run_res.status_code == 200

        first = client.get("/api/v1/notifications").json()["data"]
        assert first["unread_count"] >= 1
        ntf_id = first["items"][0]["id"]

        mark = client.post("/api/v1/notifications/read", json={"ids": [ntf_id]})
        assert mark.status_code == 200
        assert mark.json()["data"]["marked"] == 1

        second = client.get("/api/v1/notifications").json()["data"]
        matched = [it for it in second["items"] if it["id"] == ntf_id]
        assert matched and matched[0]["read"] is True
        assert second["unread_count"] == first["unread_count"] - 1

    def test_mark_all_read(self, client) -> None:
        """all=true 应标记当前全部通知已读。"""
        client.post(
            "/api/v1/run",
            json={
                "projects": [
                    {
                        "name": "All Read A",
                        "sector": "L2",
                        "stage": "testnet",
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "recent_funding": True,
                    },
                    {
                        "name": "All Read B",
                        "sector": "DeFi",
                        "stage": "testnet",
                        "has_testnet": True,
                        "has_points_program": True,
                        "no_token_yet": True,
                        "recent_funding": False,
                    },
                ],
                "enable_llm": False,
            },
        )

        before = client.get("/api/v1/notifications").json()["data"]
        assert before["unread_count"] >= 1

        mark = client.post("/api/v1/notifications/read", json={"all": True})
        assert mark.status_code == 200
        assert mark.json()["data"]["marked"] >= 1

        after = client.get("/api/v1/notifications").json()["data"]
        assert after["unread_count"] == 0
        assert all(it["read"] for it in after["items"])
