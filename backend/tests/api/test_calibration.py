"""Tests for calibration status API endpoint.

Reference:
- backend/app/routers/v1/feedback.py (GET /calibration/status)
- WEIGHT_CALIBRATION.md §3.3 / §7
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_tables():
    """每次测试前清理 feedback + weight_changelog 表。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM weight_changelog")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM weight_changelog")
        conn.commit()


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def feedback_enabled(monkeypatch):
    monkeypatch.setattr(settings, "enable_feedback_system", True)


class TestCalibrationStatus:
    def test_status_no_feedback(self, client):
        """无反馈时返回 calibration_ready=False。"""
        resp = client.get("/api/v1/calibration/status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_feedback"] == 0
        assert data["calibration_ready"] is False
        assert data["samples_needed"] == 200
        assert data["weight_version"] == settings.weight_version

    def test_status_with_feedback(self, client, feedback_enabled):
        """有反馈时统计正确。"""
        # 插入几条反馈
        for i in range(5):
            client.post(
                "/api/v1/feedback",
                json={
                    "project_id": f"test-calib-{i:03d}",
                    "signal": "useful",
                    "outcome": "airdropped" if i % 2 == 0 else None,
                },
            )

        resp = client.get("/api/v1/calibration/status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_feedback"] == 5
        assert data["strong_samples"] == 3  # 3 with outcome=airdropped
        assert data["signal_counts"]["useful"] == 5
        assert data["outcome_counts"]["airdropped"] == 3

    def test_status_with_changelog(self, client):
        """weight_changelog 记录出现在响应中。"""
        with get_connection() as conn:
            conn.execute(
                """
                INSERT INTO weight_changelog
                    (from_version, to_version, weights_json, sample_size,
                     metrics_json, triggered_by, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "v1.2",
                    "v2.0-candidate",
                    json.dumps({"airdrop_signal": 0.20}),
                    250,
                    json.dumps({"J": 0.65, "recall_farm": 0.80, "fpr_farm": 0.075}),
                    "calibrate_weights.py",
                    "candidate",
                ),
            )
            conn.commit()

        resp = client.get("/api/v1/calibration/status")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert len(data["changelog"]) == 1
        entry = data["changelog"][0]
        assert entry["from_version"] == "v1.2"
        assert entry["to_version"] == "v2.0-candidate"
        assert entry["sample_size"] == 250
        assert entry["metrics"]["J"] == 0.65
        assert entry["status"] == "candidate"
