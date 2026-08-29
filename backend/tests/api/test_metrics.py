"""Tests for the Prometheus /metrics endpoint."""

import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

from app import metrics as metrics_module
from app.main import create_app
from app.metrics import (
    AGENT_DURATION,
    AGENT_RESULTS,
    AGENT_RUNS,
    metric_sample_value,
    record_agent_run,
    record_opportunity_shadow_assessment,
)


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
                status=SimpleNamespace(value=None),
                public_label="WATCH",
                model_version="opportunity-v2.0",
                project_id="project-1",
                assessment_id="assessment-1",
                source_url="https://example.test/project-1",
                error="sensitive detail",
            )
        )

        content = client.get("/metrics").content.decode()
        assessment_sample = next(
            sample
            for family in text_string_to_metric_families(content)
            for sample in family.samples
            if sample.name == "airdrop_opportunity_shadow_assessments_total"
            and sample.labels.get("public_label") == "WATCH"
            and sample.labels.get("status") == "None"
        )

        assert assessment_sample.labels == {
            "status": "None",
            "public_label": "WATCH",
            "model_version": "opportunity-v2.0",
            "profile_version": "unknown",
        }

    def test_opportunity_shadow_project_metric_has_only_bounded_results(self, client):
        metrics_module.record_opportunity_shadow_projects(
            {result: 1 for result in metrics_module.OPPORTUNITY_SHADOW_PROJECT_RESULTS}
        )

        samples = [
            sample
            for family in text_string_to_metric_families(client.get("/metrics").text)
            for sample in family.samples
            if sample.name == "airdrop_opportunity_shadow_projects_total"
        ]

        assert {frozenset(sample.labels) for sample in samples} == {frozenset({"result"})}
        assert {sample.labels["result"] for sample in samples} == {
            "eligible",
            "sampled",
            "attempted",
            "saved",
            "failed",
            "skipped",
        }

    def test_opportunity_shadow_metric_helpers_do_not_touch_instruments_when_disabled(self, monkeypatch):
        monkeypatch.setattr(metrics_module.MetricsExporter, "is_enabled", lambda: False)
        for instrument, method in (
            (metrics_module.OPPORTUNITY_SHADOW_ENABLED, "set"),
            (metrics_module.OPPORTUNITY_SHADOW_SAMPLE_RATE, "set"),
            (metrics_module.OPPORTUNITY_SHADOW_PROJECTS, "labels"),
            (metrics_module.OPPORTUNITY_SHADOW_ASSESSMENTS, "labels"),
            (metrics_module.OPPORTUNITY_SHADOW_DURATION, "observe"),
        ):
            monkeypatch.setattr(instrument, method, Mock(side_effect=AssertionError("instrument touched")))

        metrics_module.set_opportunity_shadow_rollout(True, 1.0)
        metrics_module.record_opportunity_shadow_projects({})
        metrics_module.record_opportunity_shadow_assessment(SimpleNamespace())
        metrics_module.observe_opportunity_shadow_duration(1.0)

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


class TestAgentMetrics:
    """Agent 粒度指标（§9「Agent 粒度指标」）—— 闭合词表 + 真实递增。"""

    def test_agent_result_vocabulary_is_closed(self) -> None:
        """result 词表必须是闭合三态，非法值要抛错而非静默写脏标签。"""
        assert {"success", "error", "skipped"} == AGENT_RESULTS
        with pytest.raises(ValueError):
            record_agent_run(agent="narrative", result="timeout", duration_seconds=0.1)

    def test_record_agent_run_increments_success(self) -> None:
        before = metric_sample_value(AGENT_RUNS, agent="narrative", result="success")
        record_agent_run(agent="narrative", result="success", duration_seconds=0.25)
        after = metric_sample_value(AGENT_RUNS, agent="narrative", result="success")
        assert after == before + 1

    def test_record_agent_run_observes_duration(self) -> None:
        before = metric_sample_value(AGENT_DURATION, agent="team")
        record_agent_run(agent="team", result="success", duration_seconds=0.75)
        after = metric_sample_value(AGENT_DURATION, agent="team")
        assert after >= before + 0.75

    def test_error_and_skipped_are_distinct_labels(self) -> None:
        record_agent_run(agent="risk", result="error", duration_seconds=0.1)
        record_agent_run(agent="risk", result="skipped", duration_seconds=0.1)
        assert metric_sample_value(AGENT_RUNS, agent="risk", result="error") >= 1
        assert metric_sample_value(AGENT_RUNS, agent="risk", result="skipped") >= 1

    def test_agent_metrics_exposed(self, client) -> None:
        record_agent_run(agent="scorer", result="success", duration_seconds=0.1)
        content = client.get("/metrics").text
        assert "airdrop_agent_runs_total" in content
        assert "airdrop_agent_duration_seconds" in content
