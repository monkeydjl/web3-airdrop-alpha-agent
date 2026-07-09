"""Tests for Projects Query API endpoints.

Reference:
- backend/app/routers/v1/projects.py
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """Test client fixture."""
    app = create_app()
    return TestClient(app)


class TestListProjectsEndpoint:
    """Test GET /api/v1/projects endpoint."""

    def test_list_projects_default_params(self, client):
        """Test listing projects with default parameters."""
        response = client.get("/api/v1/projects")
        assert response.status_code == 200

        data = response.json()
        assert data["ok"] is True
        assert "data" in data

        result = data["data"]
        assert "projects" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert result["page"] == 1
        assert result["page_size"] == 20

    def test_list_projects_with_pagination(self, client):
        """Test pagination parameters."""
        response = client.get("/api/v1/projects?page=2&page_size=50")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["page"] == 2
        assert result["page_size"] == 50

    def test_list_projects_with_label_filter(self, client):
        """Test filtering by label."""
        response = client.get("/api/v1/projects?label=FARM")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["filters"]["label"] == "FARM"

    def test_list_projects_with_sector_filter(self, client):
        """Test filtering by sector."""
        response = client.get("/api/v1/projects?sector=L2")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["filters"]["sector"] == "L2"

    def test_list_projects_with_stage_filter(self, client):
        """Test filtering by stage."""
        response = client.get("/api/v1/projects?stage=testnet")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["filters"]["stage"] == "testnet"

    def test_list_projects_with_min_score(self, client):
        """Test filtering by minimum score."""
        response = client.get("/api/v1/projects?min_score=70")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["filters"]["min_score"] == 70

    def test_list_projects_with_sort_score_desc(self, client):
        """Test sorting by score descending."""
        response = client.get("/api/v1/projects?sort_by=score&sort_order=desc")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["sort"]["by"] == "score"
        assert result["sort"]["order"] == "desc"

    def test_list_projects_with_sort_name_asc(self, client):
        """Test sorting by name ascending."""
        response = client.get("/api/v1/projects?sort_by=name&sort_order=asc")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["sort"]["by"] == "name"
        assert result["sort"]["order"] == "asc"

    def test_list_projects_with_all_filters(self, client):
        """Test with multiple filters combined."""
        response = client.get(
            "/api/v1/projects?"
            "label=FARM&"
            "sector=L2&"
            "stage=testnet&"
            "min_score=80&"
            "page=1&"
            "page_size=10&"
            "sort_by=score&"
            "sort_order=desc"
        )
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        assert result["filters"]["label"] == "FARM"
        assert result["filters"]["sector"] == "L2"
        assert result["filters"]["stage"] == "testnet"
        assert result["filters"]["min_score"] == 80
        assert result["page"] == 1
        assert result["page_size"] == 10

    def test_list_projects_invalid_page_zero(self, client):
        """Test that page=0 fails validation."""
        response = client.get("/api/v1/projects?page=0")
        assert response.status_code == 422

    def test_list_projects_invalid_page_negative(self, client):
        """Test that negative page fails validation."""
        response = client.get("/api/v1/projects?page=-1")
        assert response.status_code == 422

    def test_list_projects_invalid_page_size_zero(self, client):
        """Test that page_size=0 fails validation."""
        response = client.get("/api/v1/projects?page_size=0")
        assert response.status_code == 422

    def test_list_projects_invalid_page_size_too_large(self, client):
        """Test that page_size>100 fails validation."""
        response = client.get("/api/v1/projects?page_size=101")
        assert response.status_code == 422

    def test_list_projects_invalid_min_score_negative(self, client):
        """Test that negative min_score fails validation."""
        response = client.get("/api/v1/projects?min_score=-1")
        assert response.status_code == 422

    def test_list_projects_invalid_min_score_too_large(self, client):
        """Test that min_score>100 fails validation."""
        response = client.get("/api/v1/projects?min_score=101")
        assert response.status_code == 422

    def test_list_projects_invalid_sort_by(self, client):
        """Test that invalid sort_by fails validation."""
        response = client.get("/api/v1/projects?sort_by=invalid")
        assert response.status_code == 422

    def test_list_projects_invalid_sort_order(self, client):
        """Test that invalid sort_order fails validation."""
        response = client.get("/api/v1/projects?sort_order=invalid")
        assert response.status_code == 422

    def test_list_projects_returns_empty_in_mvp(self, client):
        """Test that projects list returns data from database."""
        response = client.get("/api/v1/projects")
        assert response.status_code == 200

        data = response.json()
        result = data["data"]
        # Now returns actual data from database
        assert isinstance(result["projects"], list)
        assert isinstance(result["total"], int)
        assert result["total"] >= 0


class TestGetProjectEndpoint:
    """Test GET /api/v1/projects/{project_id} endpoint."""

    def test_get_project_returns_404_for_nonexistent(self, client):
        """Test that getting a non-existent project returns 404."""
        response = client.get("/api/v1/projects/nonexistent-project-id")
        assert response.status_code == 404

        data = response.json()
        assert "detail" in data

    def test_get_project_with_various_ids(self, client):
        """Test getting projects with different ID formats."""
        test_ids = [
            "simple-id",
            "uuid-12345678-1234-1234-1234-123456789abc",
            "project_with_underscore",
            "project-999",  # Changed to avoid collision with saved projects
        ]

        for project_id in test_ids:
            response = client.get(f"/api/v1/projects/{project_id}")
            # Should return 404 for non-existent projects
            assert response.status_code == 404


class TestProjectsResponseStructure:
    """Test response structure and format."""

    def test_response_has_required_fields(self, client):
        """Test that response has all required top-level fields."""
        response = client.get("/api/v1/projects")
        data = response.json()

        # Top level
        assert "ok" in data
        assert "data" in data

        # Data level
        result = data["data"]
        assert "projects" in result
        assert "total" in result
        assert "page" in result
        assert "page_size" in result
        assert "filters" in result
        assert "sort" in result

    def test_filters_structure(self, client):
        """Test filters object structure."""
        response = client.get(
            "/api/v1/projects?"
            "label=FARM&"
            "sector=L2&"
            "stage=testnet&"
            "min_score=70"
        )
        data = response.json()
        filters = data["data"]["filters"]

        assert "label" in filters
        assert "sector" in filters
        assert "stage" in filters
        assert "min_score" in filters

    def test_sort_structure(self, client):
        """Test sort object structure."""
        response = client.get("/api/v1/projects?sort_by=score&sort_order=desc")
        data = response.json()
        sort_info = data["data"]["sort"]

        assert "by" in sort_info
        assert "order" in sort_info

    def test_projects_list_is_array(self, client):
        """Test that projects is always an array."""
        response = client.get("/api/v1/projects")
        data = response.json()

        assert isinstance(data["data"]["projects"], list)

    def test_total_is_integer(self, client):
        """Test that total is an integer."""
        response = client.get("/api/v1/projects")
        data = response.json()

        assert isinstance(data["data"]["total"], int)
        assert data["data"]["total"] >= 0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_project_id_returns_404(self, client):
        """Test that empty project ID returns proper error."""
        response = client.get("/api/v1/projects/")
        # FastAPI will match /projects/ as list endpoint, not detail
        assert response.status_code == 200  # Matches list endpoint

    def test_special_characters_in_project_id(self, client):
        """Test project ID with special characters."""
        response = client.get("/api/v1/projects/project%20with%20spaces")
        assert response.status_code == 404

    def test_very_long_project_id(self, client):
        """Test with very long project ID."""
        long_id = "a" * 1000
        response = client.get(f"/api/v1/projects/{long_id}")
        assert response.status_code == 404

    def test_unicode_in_filters(self, client):
        """Test Unicode characters in filter values."""
        response = client.get("/api/v1/projects?sector=L2测试")
        # Should handle gracefully
        assert response.status_code == 200
