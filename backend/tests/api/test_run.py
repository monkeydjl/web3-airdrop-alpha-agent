"""Tests for Run API endpoint.

Reference:
- backend/app/routers/v1/run.py
- ENGINEERING_ROADMAP.md §8.1
"""

from unittest.mock import MagicMock, Mock

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client():
    """Test client fixture."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def sample_project():
    """Sample project input."""
    return {
        "name": "LayerX",
        "url": "https://layerx.xyz",
        "sector": "L2",
        "stage": "testnet",
        "has_testnet": True,
        "has_points_program": True,
        "no_token_yet": True,
        "recent_funding": True,
    }


class TestHealthEndpoints:
    """Test health and system endpoints."""

    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "healthy"
        assert "version" in data

    def test_version_endpoint(self, client):
        """Test version endpoint."""
        response = client.get("/version")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "version" in data["data"]
        assert "app_env" in data["data"]


class TestRunEndpoint:
    """Test /api/v1/run endpoint."""

    def test_run_single_project_success(self, client, sample_project):
        """Test running pipeline with single project."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "data" in data

        result = data["data"]
        assert "run_id" in result
        assert result["status"] in ["completed", "partial"]
        assert result["project_count"] == 1
        assert result["scored_count"] >= 0
        assert "top_projects" in result

    def test_run_reports_disabled_opportunity_shadow(self, client, sample_project, monkeypatch):
        service_factory = Mock()
        monkeypatch.setattr(settings, "opportunity_shadow_enabled", False)
        monkeypatch.setattr("app.pipeline_run.OpportunityService", service_factory)

        response = client.post(
            "/api/v1/run",
            json={"projects": [sample_project], "enable_llm": False},
        )

        assert response.status_code == 200
        assert response.json()["data"]["opportunity_shadow"] == {
            "eligible": 0,
            "sampled": 0,
            "attempted": 0,
            "saved": 0,
            "failed": 0,
            "skipped": 0,
        }
        service_factory.assert_not_called()

    def test_run_reports_enabled_opportunity_shadow(self, client, sample_project, monkeypatch):
        service = MagicMock()
        service.__enter__.return_value = service
        monkeypatch.setattr(settings, "opportunity_shadow_enabled", True)
        monkeypatch.setattr(settings, "opportunity_shadow_sample_rate", 1.0)
        monkeypatch.setattr("app.pipeline_run.OpportunityService", Mock(return_value=service))

        response = client.post(
            "/api/v1/run",
            json={"projects": [sample_project], "enable_llm": False},
        )

        data = response.json()["data"]
        assert response.status_code == 200
        assert data["opportunity_shadow"] == {
            "eligible": 1,
            "sampled": 1,
            "attempted": 1,
            "saved": 1,
            "failed": 0,
            "skipped": 0,
        }
        evaluated_row = service.evaluate_row.call_args.args[0]
        assert evaluated_row["id"] == data["top_projects"][0]["id"]
        assert evaluated_row["score"] == data["top_projects"][0]["score"]

    def test_shadow_failure_preserves_legacy_response(self, client, sample_project, monkeypatch):
        monkeypatch.setattr(settings, "opportunity_shadow_enabled", False)
        baseline = client.post(
            "/api/v1/run",
            json={"projects": [sample_project], "enable_llm": False},
        ).json()["data"]
        service = MagicMock()
        service.__enter__.return_value = service
        service.evaluate_row.side_effect = RuntimeError("shadow failed")
        monkeypatch.setattr(settings, "opportunity_shadow_enabled", True)
        monkeypatch.setattr(settings, "opportunity_shadow_sample_rate", 1.0)
        monkeypatch.setattr("app.pipeline_run.OpportunityService", Mock(return_value=service))

        response = client.post(
            "/api/v1/run",
            json={"projects": [sample_project], "enable_llm": False},
        )

        data = response.json()["data"]
        assert response.status_code == 200
        assert data["opportunity_shadow"] == {
            "eligible": 1,
            "sampled": 1,
            "attempted": 1,
            "saved": 0,
            "failed": 1,
            "skipped": 0,
        }
        for field in ("status", "project_count", "scored_count", "error_count", "top_score", "marked_processed"):
            assert data[field] == baseline[field]
        assert data["top_projects"][0]["label"] == baseline["top_projects"][0]["label"]
        assert data["top_projects"][0]["label"] in {"FARM", "WATCH", "IGNORE"}

    def test_run_multiple_projects(self, client, sample_project):
        """Test running pipeline with multiple projects."""
        projects = [
            sample_project,
            {
                "name": "RestakeDAO",
                "url": "https://restakedao.xyz",
                "sector": "Restaking",
                "stage": "mainnet",
                "has_points_program": True,
                "no_token_yet": True,
            },
        ]

        payload = {
            "projects": projects,
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["project_count"] == 2

    def test_run_returns_score_and_label(self, client, sample_project):
        """Test that response includes score and label."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        assert len(data["data"]["top_projects"]) > 0

        project = data["data"]["top_projects"][0]
        assert "score" in project
        assert "label" in project
        assert project["label"] in ["FARM", "WATCH", "IGNORE"]
        assert "confidence" in project
        assert "reason" in project
        assert isinstance(project["reason"], list)

    def test_run_includes_analysis_results(self, client, sample_project):
        """Test that response includes agent analysis results."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        project = data["data"]["top_projects"][0]

        # Should have analysis results
        assert "narrative" in project
        assert "team" in project
        assert "risk" in project
        assert "tokenomics" in project

        # Verify structure
        if project["narrative"]:
            assert "heat_score" in project["narrative"]
            assert "timing" in project["narrative"]

        if project["team"]:
            assert "team_score" in project["team"]
            assert "team_type" in project["team"]

    def test_run_minimal_project(self, client):
        """Test with minimal project data."""
        payload = {
            "projects": [
                {
                    "name": "MinimalProject",
                }
            ],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert data["data"]["project_count"] == 1

    def test_run_empty_projects_triggers_auto_collection(self, client):
        """Test that empty projects list triggers auto collection path."""
        payload = {
            "projects": [],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["status"] == "completed"
        assert "project_count" in data["data"]
        assert data["data"]["opportunity_shadow"] == {
            "eligible": 0,
            "sampled": 0,
            "attempted": 0,
            "saved": 0,
            "failed": 0,
            "skipped": 0,
        }

    def test_run_invalid_project_name_fails(self, client):
        """Test that invalid project name fails validation."""
        payload = {
            "projects": [
                {
                    "name": "",  # Empty name
                }
            ],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 422

    def test_run_too_many_projects_fails(self, client):
        """Test that too many projects fails validation."""
        payload = {
            "projects": [
                {"name": f"Project{i}"}
                for i in range(101)  # Max is 100
            ],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 422

    def test_run_with_llm_enabled(self, client, sample_project):
        """Test running with LLM enabled."""
        payload = {
            "projects": [sample_project],
            "enable_llm": True,
            "llm_model": "gpt-4o-mini",
        }

        response = client.post("/api/v1/run", json=payload)
        # Should not fail even if LLM not configured
        assert response.status_code == 200

    def test_run_preserves_project_info(self, client, sample_project):
        """Test that project info is preserved in response."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        project = data["data"]["top_projects"][0]
        assert project["name"] == sample_project["name"]
        assert project["sector"] == sample_project["sector"]
        assert project["stage"] == sample_project["stage"]

    def test_run_with_all_fields(self, client):
        """Test with all project fields populated."""
        payload = {
            "projects": [
                {
                    "name": "FullProject",
                    "url": "https://fullproject.xyz",
                    "sector": "DeFi",
                    "stage": "mainnet",
                    "has_testnet": True,
                    "has_points_program": True,
                    "no_token_yet": True,
                    "recent_funding": True,
                }
            ],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True


class TestRunResponseStructure:
    """Test response structure and format."""

    def test_response_has_required_fields(self, client, sample_project):
        """Test that response has all required fields."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        # Top level
        assert "ok" in data
        assert "data" in data

        # Data level
        result = data["data"]
        assert "run_id" in result
        assert "status" in result
        assert "project_count" in result
        assert "scored_count" in result
        assert "error_count" in result
        assert "top_projects" in result

    def test_project_result_structure(self, client, sample_project):
        """Test individual project result structure."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        project = data["data"]["top_projects"][0]

        # Required fields
        assert "id" in project
        assert "name" in project
        assert "score" in project
        assert "label" in project
        assert "confidence" in project
        assert "reason" in project

        # Types
        assert isinstance(project["score"], int)
        assert isinstance(project["label"], str)
        assert isinstance(project["confidence"], float)
        assert isinstance(project["reason"], list)

    def test_run_id_format(self, client, sample_project):
        """Test run_id format."""
        payload = {
            "projects": [sample_project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        data = response.json()

        run_id = data["data"]["run_id"]
        assert run_id.startswith("api-run-")
        assert len(run_id) > 15  # Should include timestamp


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_missing_request_body(self, client):
        """Test request without body."""
        response = client.post("/api/v1/run")
        assert response.status_code == 422

    def test_invalid_json(self, client):
        """Test with invalid JSON."""
        response = client.post(
            "/api/v1/run",
            content="invalid json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 422

    def test_extra_fields_ignored(self, client, sample_project):
        """Test that extra fields are ignored."""
        project = {**sample_project, "extra_field": "should be ignored"}
        payload = {
            "projects": [project],
            "enable_llm": False,
        }

        response = client.post("/api/v1/run", json=payload)
        # Should succeed (extra fields ignored by Pydantic)
        assert response.status_code == 200
