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


def _histogram_sum(metric) -> float:
    """读取 histogram 的 `_sum` 样本 —— `metric_sample_value` 对 histogram 返回
    的是 `_count`（观测次数）而非观测值之和，验证"观察到了什么值"要用这个。"""
    for family in metric.collect():
        for sample in family.samples:
            if sample.name.endswith("_sum"):
                return float(sample.value)
    return 0.0


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

    def test_http_request_duration_histogram_observed(self, client):
        """入站 API 请求耗时 histogram 在每次请求后被 observe（§9）。"""
        from app.metrics import HTTP_DURATION, metric_sample_value

        before = metric_sample_value(HTTP_DURATION)
        client.get("/health")
        after = metric_sample_value(HTTP_DURATION)
        assert after > before

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


class TestBusinessPanelMetrics:
    """业务面板三信号（§9「业务面板」）：评分 / 赛道热度 / 反馈。"""

    def test_record_project_score_observes(self) -> None:
        from app.metrics import PROJECT_SCORE, record_project_score

        before = _histogram_sum(PROJECT_SCORE)
        record_project_score(75.0)
        after = _histogram_sum(PROJECT_SCORE)
        assert after == before + 75.0

    def test_record_narrative_heat_score_observes(self) -> None:
        from app.metrics import NARRATIVE_HEAT_SCORE, record_narrative_heat_score

        before = _histogram_sum(NARRATIVE_HEAT_SCORE)
        record_narrative_heat_score(0.85)
        after = _histogram_sum(NARRATIVE_HEAT_SCORE)
        assert after == before + 0.85

    def test_project_score_clamped_to_range(self) -> None:
        from app.metrics import PROJECT_SCORE, record_project_score

        before = _histogram_sum(PROJECT_SCORE)
        record_project_score(250.0)  # 越界 → 钳到 100
        record_project_score(-30.0)  # 越界 → 钳到 0
        after = _histogram_sum(PROJECT_SCORE)
        # 100 + 0 = 100
        assert after == before + 100.0

    def test_feedback_signal_vocabulary_is_closed(self) -> None:
        from app.metrics import FEEDBACK_SIGNALS, record_feedback

        assert {"useful", "useless", "wrong_label", "correct_outcome"} == FEEDBACK_SIGNALS
        with pytest.raises(ValueError):
            record_feedback(signal="not_a_signal")

    def test_record_feedback_increments_by_signal(self) -> None:
        from app.metrics import FEEDBACK_TOTAL, metric_sample_value, record_feedback

        before = metric_sample_value(FEEDBACK_TOTAL, signal="useful")
        record_feedback(signal="useful")
        after = metric_sample_value(FEEDBACK_TOTAL, signal="useful")
        assert after == before + 1


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
        # metric_sample_value 对 histogram 返回 `_count`（观测次数），
        # 这里断言"发生了一次 observe"即可（值是否钳 ≥0 由 record_agent_run 保证）。
        assert after == before + 1

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
