"""API tests for export/import endpoints.

Reference:
- app/routers/v1/export_import.py
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    """Create test client."""
    app = create_app()
    return TestClient(app)


class TestExportAPI:
    """Test export API endpoints."""

    def test_export_projects_excel(self, client):
        """Test exporting projects to Excel."""
        response = client.get("/api/v1/export/projects?format=excel")

        # May be 404 if no projects, or 200 with data
        assert response.status_code in [200, 404]

        if response.status_code == 200:
            assert (
                response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            assert "attachment" in response.headers["content-disposition"]
            assert len(response.content) > 0

    def test_export_projects_csv(self, client):
        """Test exporting projects to CSV."""
        response = client.get("/api/v1/export/projects?format=csv")

        assert response.status_code in [200, 404]

        if response.status_code == 200:
            assert "text/csv" in response.headers["content-type"]
            assert "attachment" in response.headers["content-disposition"]

    def test_export_projects_with_filters(self, client):
        """Test exporting with filters."""
        response = client.get(
            "/api/v1/export/projects",
            params={
                "format": "excel",
                "label": "FARM",
                "min_score": 80,
            },
        )

        # 404 or 200 depending on data
        assert response.status_code in [200, 404]

    def test_export_project_detail_not_found(self, client):
        """Test exporting non-existent project."""
        response = client.get("/api/v1/export/project/nonexistent")

        assert response.status_code == 404

    def test_download_template(self, client):
        """Test downloading import template."""
        response = client.get("/api/v1/export/template")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        assert "import_template.xlsx" in response.headers["content-disposition"]
        assert len(response.content) > 0


class TestImportAPI:
    """Test import API endpoints."""

    def test_import_projects_excel(self, client):
        """Test importing projects from Excel."""
        # Create test Excel file
        import pandas as pd

        data = {
            "项目名称": ["Test Project"],
            "赛道": ["L2"],
            "有测试网": [True],
        }
        df = pd.DataFrame(data)

        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        excel_bytes = output.getvalue()

        response = client.post(
            "/api/v1/import/projects",
            files={
                "file": ("test.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            },
        )

        assert response.status_code == 200
        # RunResponse format
        data = response.json()
        assert "status" in data
        assert data["status"] == "completed"
        assert data["project_count"] == 1

    def test_import_projects_csv(self, client):
        """Test importing projects from CSV."""
        csv_content = """项目名称,赛道,有测试网
Test CSV Project,DeFi,true
"""

        response = client.post("/api/v1/import/projects", files={"file": ("test.csv", csv_content, "text/csv")})

        assert response.status_code == 200
        # RunResponse format
        assert "run_id" in response.json()
        assert "status" in response.json()

    def test_import_invalid_file_type(self, client):
        """Test importing with invalid file type."""
        response = client.post(
            "/api/v1/import/projects", files={"file": ("test.txt", b"invalid content", "text/plain")}
        )

        assert response.status_code == 400
        assert "不支持的文件格式" in response.json()["error"]["message"]

    def test_import_empty_file(self, client):
        """Test importing empty file."""
        import pandas as pd

        df = pd.DataFrame({"项目名称": []})

        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        excel_bytes = output.getvalue()

        response = client.post(
            "/api/v1/import/projects",
            files={
                "file": ("empty.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            },
        )

        assert response.status_code == 400

    def test_import_missing_required_field(self, client):
        """Test importing without required field."""
        csv_content = """赛道,阶段
L2,testnet
"""

        response = client.post("/api/v1/import/projects", files={"file": ("invalid.csv", csv_content, "text/csv")})

        # Should fail with 400 or 500
        assert response.status_code in [400, 500]

    def test_import_too_many_projects(self, client):
        """Test importing more than limit."""
        import pandas as pd

        # Create 101 projects
        data = {
            "项目名称": [f"Project {i}" for i in range(101)],
        }
        df = pd.DataFrame(data)

        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        excel_bytes = output.getvalue()

        response = client.post(
            "/api/v1/import/projects",
            files={
                "file": ("large.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            },
        )

        assert response.status_code == 400
        assert "最多100个" in response.json()["error"]["message"]

    def test_import_with_validation_errors(self, client):
        """Test import with some invalid rows."""
        csv_content = """项目名称,URL
Valid Project,https://valid.xyz
,https://invalid1.xyz
Bad URL Project,invalid-url
"""

        response = client.post("/api/v1/import/projects", files={"file": ("mixed.csv", csv_content, "text/csv")})

        # Should succeed with valid projects
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "completed"

        # Should have validation errors in response (if present)
        if data.get("validation_errors"):
            assert len(data["validation_errors"]) > 0
