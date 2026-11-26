"""Tests for calibration status API endpoint.

Reference:
- backend/app/routers/v1/feedback.py (GET /calibration/status)
- WEIGHT_CALIBRATION.md §3.3 / §7
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.calibration import WEIGHT_KEYS
from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture(autouse=True)
def clean_tables():
    """每次测试前后清理 feedback / weight_changelog / roi_outcomes 表。"""
    with get_connection() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM weight_changelog")
        conn.execute("DELETE FROM roi_outcomes")
        conn.commit()
    yield
    with get_connection() as conn:
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM weight_changelog")
        conn.execute("DELETE FROM roi_outcomes")
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

    def test_status_gate_matches_engine_sample_extraction(self, client, feedback_enabled):
        """gate 字段必须走校准引擎口径：反馈条数 ≠ 有效样本数。"""
        subscores = json.dumps({k: 60.0 for k in WEIGHT_KEYS})
        with get_connection() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, name, score, label, sub_scores) VALUES (?, ?, ?, ?, ?)",
                ("p-gate", "Gate Project", 80, "FARM", subscores),
            )
            conn.commit()
            # 一条反馈挂在没有子分的项目上：不得计入有效样本
            conn.execute(
                "INSERT OR REPLACE INTO projects (id, name, score, label) VALUES (?, ?, ?, ?)",
                ("p-gate-nosub", "No Subscores", 70, "WATCH"),
            )
            conn.commit()

        client.post(
            "/api/v1/feedback",
            json={"project_id": "p-gate", "signal": "correct_outcome", "outcome": "airdropped"},
        )
        client.post(
            "/api/v1/feedback",
            json={"project_id": "p-gate-nosub", "signal": "correct_outcome", "outcome": "not_airdropped"},
        )

        data = client.get("/api/v1/calibration/status").json()["data"]
        assert data["total_feedback"] == 2
        gate = data["gate"]
        assert gate["live_samples"] == 1
        assert gate["farm_samples"] == 1
        assert gate["min_live_samples"] == 200
        assert gate["min_farm_samples"] == 30
        assert gate["samples_needed"] == 199
        assert gate["farm_samples_needed"] == 29
        assert gate["passed"] is False
        assert gate["total_by_source"] == {"live": 1, "backtest": 0}
        # 两条结果标记同时写进收益台账（manual）—— 但门禁只数引擎提取的 live
        # 样本，台账计数是另一条口径，二者不混算。
        assert data["roi_ledger"]["event_counts"] == {"airdrop_received": 1, "airdrop_missed": 1}
        assert data["roi_ledger"]["manual_signal_samples"] == 2
        assert data["roi_ledger"]["signal_samples_by_source"] == {"live": 2, "backtest": 0}

    def test_status_gate_counts_roi_ledger_signals(self, client, feedback_enabled):
        """收益台账的到账/未领记录单独统计，不与反馈混算。"""
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO roi_outcomes (user_id, project_id, event, source) VALUES (?, ?, ?, ?)",
                ("default", "p-roi", "airdrop_received", "manual"),
            )
            conn.execute(
                "INSERT INTO roi_outcomes (user_id, project_id, event, source) VALUES (?, ?, ?, ?)",
                ("default", "p-roi2", "airdrop_missed", "manual"),
            )
            conn.commit()

        data = client.get("/api/v1/calibration/status").json()["data"]
        assert data["roi_ledger"]["event_counts"]["airdrop_received"] == 1
        assert data["roi_ledger"]["event_counts"]["airdrop_missed"] == 1
        assert data["roi_ledger"]["manual_signal_samples"] == 2
        assert data["roi_ledger"]["signal_samples_by_source"] == {"live": 2, "backtest": 0}

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
