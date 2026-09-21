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

    def test_feedback_wrong_label_upgrades_project_to_farm(self, client, feedback_enabled) -> None:
        """测试人工核验将 veto=no_participation_path 的项目升级为 FARM 并持久化落库。"""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, score, label, veto, reason)
                VALUES ('test-p1', 'Test Project 1', 75, 'WATCH', 'no_participation_path', '["no verified participation path"]')
                """
            )
            conn.commit()

        response = client.post(
            "/api/v1/feedback",
            json={
                "project_id": "test-p1",
                "signal": "wrong_label",
                "note": "FARM",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["updated_label"] == "FARM"
        assert data["updated_veto"] is None

        # 验证数据库持久化
        with get_connection() as conn:
            row = conn.execute("SELECT label, veto, reason FROM projects WHERE id = 'test-p1'").fetchone()
            assert row["label"] == "FARM"
            assert row["veto"] is None
            assert "已发现参与路径" in row["reason"]

    def test_feedback_wrong_label_verifies_watch(self, client, feedback_enabled) -> None:
        """测试人工核验确认无路径维持观察，veto 更新为 verified_no_path，消除待验证提示。"""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, score, label, veto, reason)
                VALUES ('test-p2', 'Test Project 2', 72, 'WATCH', 'no_participation_path', '["no verified participation path"]')
                """
            )
            conn.commit()

        response = client.post(
            "/api/v1/feedback",
            json={
                "project_id": "test-p2",
                "signal": "wrong_label",
                "note": "WATCH",
            },
        )
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["updated_label"] == "WATCH"
        assert data["updated_veto"] == "verified_no_path"

        # 验证数据库持久化
        with get_connection() as conn:
            row = conn.execute("SELECT label, veto, reason FROM projects WHERE id = 'test-p2'").fetchone()
            assert row["label"] == "WATCH"
            assert row["veto"] == "verified_no_path"
            assert "维持观察" in row["reason"]

    def test_feedback_airdropped_marks_project_ended(self, client, feedback_enabled) -> None:
        """测试复盘反馈 outcome 为 airdropped 时，项目主表同步置为 ended + already_launched。"""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, score, label, stage, veto, reason)
                VALUES ('test-p-airdrop', 'Test Airdrop Project', 80, 'FARM', 'mainnet', NULL, '["活跃参与中"]')
                """
            )
            conn.commit()

        response = client.post(
            "/api/v1/feedback",
            json={
                "project_id": "test-p-airdrop",
                "signal": "correct_outcome",
                "outcome": "airdropped",
            },
        )
        assert response.status_code == 200

        with get_connection() as conn:
            row = conn.execute("SELECT stage, veto, reason FROM projects WHERE id = 'test-p-airdrop'").fetchone()
            assert row["stage"] == "ended"
            assert row["veto"] == "already_launched"
            assert "已完成空投" in row["reason"]

    def test_feedback_batch_airdropped_marks_project_ended(self, client, feedback_enabled) -> None:
        """测试批量复盘反馈 outcome 为 airdropped 时，项目主表同步置为 ended + already_launched。"""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO projects (id, name, score, label, stage, veto, reason)
                VALUES ('test-p-batch', 'Test Batch Airdrop', 75, 'FARM', 'testnet', NULL, '["参与中"]')
                """
            )
            conn.commit()

        response = client.post(
            "/api/v1/feedback/batch",
            json={
                "items": [
                    {
                        "project_id": "test-p-batch",
                        "signal": "correct_outcome",
                        "outcome": "airdropped",
                    }
                ]
            },
        )
        assert response.status_code == 200

        with get_connection() as conn:
            row = conn.execute("SELECT stage, veto, reason FROM projects WHERE id = 'test-p-batch'").fetchone()
            assert row["stage"] == "ended"
            assert row["veto"] == "already_launched"
            assert "已完成空投" in row["reason"]


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
