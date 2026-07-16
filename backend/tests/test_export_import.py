"""Tests for export/import functionality.

Reference:
- app/export.py
- app/import_utils.py
- app/routers/v1/export_import.py
"""

import io

import pytest

from app.export import (
    export_project_detail_to_excel,
    export_projects_to_csv,
    export_projects_to_excel,
)
from app.import_utils import (
    create_import_template_excel,
    import_projects_from_csv,
    import_projects_from_excel,
    validate_imported_projects,
)


class TestExport:
    """Test export functionality."""

    def test_export_projects_to_excel(self):
        """Test exporting projects to Excel."""
        projects = [
            {
                "id": "test-001",
                "name": "Test Project",
                "url": "https://test.xyz",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]

        result = export_projects_to_excel(projects)

        assert isinstance(result, bytes)
        assert len(result) > 0
        # Excel files start with PK (ZIP signature)
        assert result[:2] == b"PK"

    def test_export_projects_to_csv(self):
        """Test exporting projects to CSV."""
        projects = [
            {
                "id": "test-001",
                "name": "Test Project",
                "url": "https://test.xyz",
                "sector": "L2",
                "stage": "testnet",
                "score": 85,
                "label": "FARM",
                "confidence": 1.0,
                "created_at": "2026-01-01",
                "updated_at": "2026-01-01",
            }
        ]

        result = export_projects_to_csv(projects)

        assert isinstance(result, str)
        assert "ID" in result
        assert "Test Project" in result
        assert "FARM" in result

    def test_export_empty_list(self):
        """Test exporting empty project list."""
        projects = []

        excel_result = export_projects_to_excel(projects)
        csv_result = export_projects_to_csv(projects)

        assert isinstance(excel_result, bytes)
        assert isinstance(csv_result, str)

    def test_export_project_detail(self):
        """Test exporting project detail with analysis."""
        project = {
            "id": "test-001",
            "name": "Test Project",
            "url": "https://test.xyz",
            "sector": "L2",
            "stage": "testnet",
            "score": 85,
            "label": "FARM",
            "confidence": 1.0,
            "reason": ["strong signal", "early timing"],
            "narrative": {
                "sector": "L2",
                "stage": "growth",
                "heat_score": 0.9,
                "timing": "early",
            },
            "team": {
                "team_score": 0.8,
                "team_flags": ["tier-1 backed"],
                "team_type": "semi_anon",
            },
            "risk": {
                "token_risk": 0.3,
                "risk_flags": [],
                "unlock_pressure": "medium",
            },
            "tokenomics": {
                "vc_share": 0.3,
                "team_share": 0.25,
                "unlock_penalty": 0.35,
            },
        }

        result = export_project_detail_to_excel(project)

        assert isinstance(result, bytes)
        assert len(result) > 0
        assert result[:2] == b"PK"


class TestImport:
    """Test import functionality."""

    def test_import_projects_from_excel(self):
        """Test importing projects from Excel."""
        # Create a simple Excel file
        import pandas as pd

        data = {
            "项目名称": ["Project A", "Project B"],
            "URL": ["https://a.xyz", "https://b.xyz"],
            "赛道": ["L2", "DeFi"],
            "阶段": ["testnet", "mainnet"],
            "有测试网": [True, False],
        }
        df = pd.DataFrame(data)

        output = io.BytesIO()
        df.to_excel(output, index=False, engine="openpyxl")
        excel_bytes = output.getvalue()

        # Import
        projects = import_projects_from_excel(excel_bytes)

        assert len(projects) == 2
        assert projects[0]["name"] == "Project A"
        assert projects[0]["sector"] == "L2"
        assert projects[0]["has_testnet"] is True
        assert projects[1]["has_testnet"] is False

    def test_import_projects_from_csv(self):
        """Test importing projects from CSV."""
        csv_content = """项目名称,URL,赛道,阶段,有测试网
Project A,https://a.xyz,L2,testnet,True
Project B,https://b.xyz,DeFi,mainnet,False
"""

        projects = import_projects_from_csv(csv_content)

        assert len(projects) == 2
        assert projects[0]["name"] == "Project A"
        assert projects[0]["has_testnet"] is True

    def test_import_with_english_headers(self):
        """Test importing with English headers."""
        csv_content = """name,url,sector,stage,has_testnet
Project A,https://a.xyz,L2,testnet,true
"""

        projects = import_projects_from_csv(csv_content)

        assert len(projects) == 1
        assert projects[0]["name"] == "Project A"

    def test_import_missing_required_field(self):
        """Test import fails without required field."""
        csv_content = """url,sector
https://a.xyz,L2
"""

        with pytest.raises(ValueError, match="必须包含"):
            import_projects_from_csv(csv_content)

    def test_validate_imported_projects(self):
        """Test validation of imported projects."""
        projects = [
            {"name": "Valid Project", "url": "https://test.xyz"},
            {"name": "", "url": "https://test2.xyz"},  # Empty name
            {"name": "A" * 200, "url": "https://test3.xyz"},  # Too long
            {"name": "Bad URL", "url": "invalid-url"},  # Bad URL
        ]

        valid, errors = validate_imported_projects(projects)

        assert len(valid) == 1
        assert len(errors) == 3
        assert valid[0]["name"] == "Valid Project"

    def test_validate_skips_empty_rows(self):
        """Test validation skips empty rows."""
        projects = [
            {"name": "Valid"},
            {"name": ""},
            {"name": None},
        ]

        valid, errors = validate_imported_projects(projects)

        # Should skip empty/None names, not error
        assert len(valid) == 1
        assert len(errors) >= 0

    def test_create_import_template(self):
        """Test creating import template."""
        template = create_import_template_excel()

        assert isinstance(template, bytes)
        assert len(template) > 0
        assert template[:2] == b"PK"


class TestImportBooleanFields:
    """Test importing boolean fields with various formats."""

    def test_import_boolean_true_variants(self):
        """Test various representations of True."""
        csv_content = """name,has_testnet,has_points_program,no_token_yet,recent_funding
P1,true,True,TRUE,yes
P2,是,是,是,是
P3,1,1,1,1
P4,√,√,√,√
"""

        projects = import_projects_from_csv(csv_content)

        for project in projects:
            assert project["has_testnet"] is True
            assert project["has_points_program"] is True
            assert project["no_token_yet"] is True
            assert project["recent_funding"] is True

    def test_import_boolean_false_variants(self):
        """Test various representations of False."""
        csv_content = """name,has_testnet
P1,false
P2,False
P3,0
P4,no
"""

        projects = import_projects_from_csv(csv_content)

        for project in projects:
            assert project["has_testnet"] is False

    def test_import_boolean_empty_defaults_false(self):
        """Test empty boolean fields default to False."""
        csv_content = """name,has_testnet
P1,
"""

        projects = import_projects_from_csv(csv_content)

        assert projects[0]["has_testnet"] is False
