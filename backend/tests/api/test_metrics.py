"""Tests for the Prometheus /metrics endpoint."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app import metrics as metrics_module
from app.metrics import record_opportunity_shadow_assessment


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
        for metric_name in (
            "airdrop_opportunity_shadow_projects_total",
            "airdrop_opportunity_shadow_assessments_total",
            "airdrop_opportunity_shadow_duration_seconds",
            "airdrop_opportunity_shadow_enabled",
            "airdrop_opportunity_shadow_sample_rate",
        ):
            assert metric_name in content

    def test_opportunity_shadow_assessment_metrics_use_bounded_labels(self, client):
        record_opportunity_shadow_assessment(
            SimpleNamespace(
                status="MONITOR",
                public_label="WATCH",
                model_version="opportunity-v2.0",
                profile_version="low-cost-curated-multiwallet-v1",
                project_id="project-1",
                assessment_id="assessment-1",
                source_url="https://example.test/project-1",
                error="sensitive detail",
            )
        )

        content = client.get("/metrics").content.decode()
        assessment_line = next(
            line
            for line in content.splitlines()
            if line.startswith("airdrop_opportunity_shadow_assessments_total{")
        )

        for label_name in ("status", "public_label", "model_version", "profile_version"):
            assert f'{label_name}="' in assessment_line
        for forbidden_label in ("project_id", "assessment_id", "source_url", "error"):
            assert f'{forbidden_label}="' not in assessment_line

    def test_opportunity_shadow_metric_helpers_isolate_enabled_check_failure(self, monkeypatch):
        monkeypatch.setattr(
            metrics_module.MetricsExporter,
            "is_enabled",
            Mock(side_effect=RuntimeError("metrics failed")),
        )

        metrics_module.set_opportunity_shadow_rollout(True, 1.0)
        metrics_module.record_opportunity_shadow_projects({})
        metrics_module.record_opportunity_shadow_assessment(SimpleNamespace())
        metrics_module.observe_opportunity_shadow_duration(1.0)

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
