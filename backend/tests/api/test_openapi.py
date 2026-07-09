"""Tests for OpenAPI documentation and schema.

Reference:
- backend/app/openapi.py
- backend/app/main.py
"""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """Test client fixture."""
    app = create_app()
    return TestClient(app)


class TestOpenAPIEndpoints:
    """Test OpenAPI documentation endpoints."""

    def test_openapi_json_accessible(self, client):
        """Test that /openapi.json is accessible."""
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"

    def test_docs_page_accessible(self, client):
        """Test that /docs (Swagger UI) is accessible."""
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_redoc_page_accessible(self, client):
        """Test that /redoc is accessible."""
        response = client.get("/redoc")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


class TestOpenAPISchema:
    """Test OpenAPI schema structure and content."""

    def test_schema_has_required_fields(self, client):
        """Test that schema has all required OpenAPI fields."""
        response = client.get("/openapi.json")
        schema = response.json()

        # OpenAPI 3.x required fields
        assert "openapi" in schema
        assert schema["openapi"].startswith("3.")
        assert "info" in schema
        assert "paths" in schema

    def test_info_section(self, client):
        """Test API info section."""
        response = client.get("/openapi.json")
        schema = response.json()
        info = schema["info"]

        assert "title" in info
        assert "version" in info
        assert "description" in info
        assert info["title"] == "Web3 Airdrop Alpha Agent System"

    def test_contact_info(self, client):
        """Test contact information."""
        response = client.get("/openapi.json")
        schema = response.json()
        info = schema["info"]

        assert "contact" in info
        assert "name" in info["contact"]
        assert "url" in info["contact"]

    def test_license_info(self, client):
        """Test license information."""
        response = client.get("/openapi.json")
        schema = response.json()
        info = schema["info"]

        assert "license" in info
        assert info["license"]["name"] == "MIT"

    def test_servers_defined(self, client):
        """Test that servers are defined."""
        response = client.get("/openapi.json")
        schema = response.json()

        assert "servers" in schema
        assert len(schema["servers"]) > 0

        # Check server structure
        server = schema["servers"][0]
        assert "url" in server
        assert "description" in server


class TestAPIEndpointsInSchema:
    """Test that all API endpoints are documented."""

    def test_run_endpoint_documented(self, client):
        """Test that POST /api/v1/run is documented."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]

        assert "/api/v1/run" in paths
        assert "post" in paths["/api/v1/run"]

    def test_projects_list_endpoint_documented(self, client):
        """Test that GET /api/v1/projects is documented."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]

        assert "/api/v1/projects" in paths
        assert "get" in paths["/api/v1/projects"]

    def test_project_detail_endpoint_documented(self, client):
        """Test that GET /api/v1/projects/{project_id} is documented."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]

        assert "/api/v1/projects/{project_id}" in paths
        assert "get" in paths["/api/v1/projects/{project_id}"]

    def test_health_endpoint_documented(self, client):
        """Test that GET /health is documented."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]

        assert "/health" in paths
        assert "get" in paths["/health"]

    def test_version_endpoint_documented(self, client):
        """Test that GET /version is documented."""
        response = client.get("/openapi.json")
        schema = response.json()
        paths = schema["paths"]

        assert "/version" in paths
        assert "get" in paths["/version"]


class TestEndpointDetails:
    """Test endpoint documentation details."""

    def test_run_endpoint_has_summary(self, client):
        """Test that /run endpoint has summary and description."""
        response = client.get("/openapi.json")
        schema = response.json()
        endpoint = schema["paths"]["/api/v1/run"]["post"]

        assert "summary" in endpoint
        assert "description" in endpoint
        assert len(endpoint["description"]) > 50  # Has substantial description

    def test_run_endpoint_has_request_body(self, client):
        """Test that /run endpoint has request body schema."""
        response = client.get("/openapi.json")
        schema = response.json()
        endpoint = schema["paths"]["/api/v1/run"]["post"]

        assert "requestBody" in endpoint
        assert "content" in endpoint["requestBody"]
        assert "application/json" in endpoint["requestBody"]["content"]

    def test_run_endpoint_has_responses(self, client):
        """Test that /run endpoint has response schemas."""
        response = client.get("/openapi.json")
        schema = response.json()
        endpoint = schema["paths"]["/api/v1/run"]["post"]

        assert "responses" in endpoint
        assert "200" in endpoint["responses"]
        assert "400" in endpoint["responses"]
        assert "500" in endpoint["responses"]

    def test_projects_endpoint_has_parameters(self, client):
        """Test that /projects endpoint has query parameters."""
        response = client.get("/openapi.json")
        schema = response.json()
        endpoint = schema["paths"]["/api/v1/projects"]["get"]

        assert "parameters" in endpoint
        params = endpoint["parameters"]

        # Check for key parameters
        param_names = [p["name"] for p in params]
        assert "page" in param_names
        assert "page_size" in param_names
        assert "label" in param_names
        assert "sector" in param_names
        assert "sort_by" in param_names


class TestTags:
    """Test API tags for grouping."""

    def test_tags_defined(self, client):
        """Test that tags are defined."""
        response = client.get("/openapi.json")
        schema = response.json()

        assert "tags" in schema
        assert len(schema["tags"]) > 0

    def test_system_tag_exists(self, client):
        """Test that 'system' tag exists."""
        response = client.get("/openapi.json")
        schema = response.json()

        tag_names = [tag["name"] for tag in schema["tags"]]
        assert "system" in tag_names

    def test_pipeline_tag_exists(self, client):
        """Test that 'pipeline' tag exists."""
        response = client.get("/openapi.json")
        schema = response.json()

        tag_names = [tag["name"] for tag in schema["tags"]]
        assert "pipeline" in tag_names

    def test_projects_tag_exists(self, client):
        """Test that 'projects' tag exists."""
        response = client.get("/openapi.json")
        schema = response.json()

        tag_names = [tag["name"] for tag in schema["tags"]]
        assert "projects" in tag_names

    def test_tags_have_descriptions(self, client):
        """Test that tags have descriptions."""
        response = client.get("/openapi.json")
        schema = response.json()

        for tag in schema["tags"]:
            assert "name" in tag
            assert "description" in tag
            assert len(tag["description"]) > 0


class TestSecuritySchemes:
    """Test security scheme definitions."""

    def test_security_schemes_defined(self, client):
        """Test that security schemes are defined."""
        response = client.get("/openapi.json")
        schema = response.json()

        assert "components" in schema
        assert "securitySchemes" in schema["components"]

    def test_api_key_auth_defined(self, client):
        """Test that API Key auth is defined (for future use)."""
        response = client.get("/openapi.json")
        schema = response.json()
        schemes = schema["components"]["securitySchemes"]

        assert "ApiKeyAuth" in schemes
        assert schemes["ApiKeyAuth"]["type"] == "apiKey"
        assert schemes["ApiKeyAuth"]["in"] == "header"


class TestSchemaComponents:
    """Test reusable schema components."""

    def test_components_defined(self, client):
        """Test that components section exists."""
        response = client.get("/openapi.json")
        schema = response.json()

        assert "components" in schema
        assert "schemas" in schema["components"]

    def test_request_models_defined(self, client):
        """Test that request models are in components."""
        response = client.get("/openapi.json")
        schema = response.json()
        schemas = schema["components"]["schemas"]

        # Check for key request models
        assert "RunRequest" in schemas
        assert "ProjectInput" in schemas

    def test_response_models_defined(self, client):
        """Test that response models are in components."""
        response = client.get("/openapi.json")
        schema = response.json()
        schemas = schema["components"]["schemas"]

        # Check for key response models (may have module prefix)
        assert any("RunResponse" in name for name in schemas)
        assert "ProjectsResponse" in schemas
        assert "ErrorResponse" in schemas
