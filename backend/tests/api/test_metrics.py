"""Tests for the Prometheus /metrics endpoint."""

import time

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


class TestMetricsEndpoint:
    def test_metrics_returns_prometheus_format(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert b"# HELP" in response.content

    def test_metrics_contains_airdrop_metrics(self, client):
        response = client.get("/metrics")
        assert response.status_code == 200
        content = response.content.decode()
        assert "airdrop_pipeline_runs_total" in content
        assert "airdrop_collection_runs_total" in content
        assert "airdrop_db_projects_total" in content

    def test_health_check_still_works(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["ok"] is True

    def test_metrics_disabled_returns_404(self, monkeypatch, client):
        from app import metrics as metrics_module

        monkeypatch.setattr(metrics_module.MetricsExporter, "is_enabled", lambda: False)
        response = client.get("/metrics")
        assert response.status_code == 404
        assert response.json()["ok"] is False

    def test_pipeline_run_increments_metrics(self, client):
        # Parse current counter value
        response = client.get("/metrics")
        content = response.content.decode()
        before = self._parse_counter(content, "airdrop_pipeline_runs_total", 'trigger="manual"')

        payload = {
            "projects": [
                {
                    "name": "NovaLayer",
                    "sector": "L2",
                    "stage": "testnet",
                    "has_testnet": True,
                    "has_points_program": True,
                    "no_token_yet": True,
                }
            ]
        }
        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200

        # Counters are global; give a short moment for observation to settle
        time.sleep(0.1)
        response = client.get("/metrics")
        content = response.content.decode()
        after = self._parse_counter(content, "airdrop_pipeline_runs_total", 'trigger="manual"')
        assert after >= before + 1

    @staticmethod
    def _parse_counter(content: str, name: str, label_selector: str = "") -> int:
        for line in content.splitlines():
            if line.startswith(name) and label_selector in line:
                # Format: name{label="value"} 5
                parts = line.split()
                if len(parts) == 2:
                    return int(float(parts[1]))
        return 0
