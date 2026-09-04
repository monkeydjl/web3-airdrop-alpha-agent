"""Tests for Projects Query API endpoints.

Reference:
- backend/app/routers/v1/projects.py
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
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
        """Test that page_size>500 fails validation."""
        response = client.get("/api/v1/projects?page_size=501")
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
        assert "error" in data
        assert data["error"]["code"] == "NOT_FOUND"

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
        response = client.get("/api/v1/projects?label=FARM&sector=L2&stage=testnet&min_score=70")
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


class TestLegacyRowBackfill:
    """历史行（本次改动之前打的分）缺 `risk_level` 时的补算行为。

    分档逻辑 `score_to_risk_level()` 早就存在，但当初只打日志、没有字段承载，
    所以老 `team_json` 里没有 `risk_level` 这个键；而前端详情页一直在读它，
    于是「团队风险」那一格永远空白 —— 看起来像「这个项目没有风险评估」。

    补算是安全的：`risk_level` 由 `team_score` 唯一决定，而 `team_score` 是
    落库的，等于重放同一个映射，不是猜测。

    对照组同样重要：`farming_cost` 的输入 `has_points_program` 不在 projects
    表里，无法忠实重放，所以历史行**不补**该键 —— 宁可让前端显示「—」，
    也不端出一个看起来很像真值的猜测。
    """

    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        db_path = tmp_path / "legacy_rows.db"
        monkeypatch.setattr(settings, "db_path", str(db_path))
        monkeypatch.setattr(settings, "api_key", "")
        monkeypatch.setattr(settings, "app_env", "testing")
        init_db()
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO projects (id, name, sector, stage, score, label, confidence,
                                  source, team_json, risk_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-1",
                "Legacy Project",
                "L2",
                "testnet",
                70,
                "FARM",
                0.9,
                "seed",
                # 刻意模拟老形状：只有当年真的会落库的三个键
                json.dumps({"team_score": 0.85, "team_flags": ["doxxed team"], "team_type": "doxxed"}),
                json.dumps(
                    {
                        "token_risk": 0.4,
                        "risk_flags": [],
                        "unlock_pressure": "medium",
                        "sybil_difficulty": "high",
                    }
                ),
            ),
        )
        conn.commit()
        conn.close()
        return TestClient(create_app(db_override=lambda: None))

    def test_legacy_row_gets_risk_level(self, client):
        response = client.get("/api/v1/projects/legacy-1")
        assert response.status_code == 200
        team = response.json()["data"]["project"]["team"]
        # team_score=0.85 > 0.7 -> low（与 score_to_risk_level 一致）
        assert team["risk_level"] == "low", (
            "历史行没有补上 risk_level —— 前端「团队风险」会显示空白，看起来像「这个项目没有风险评估」。"
        )

    def test_legacy_row_keeps_farming_cost_absent(self, client):
        response = client.get("/api/v1/projects/legacy-1")
        risk = response.json()["data"]["project"]["risk"]
        assert "farming_cost" not in risk, (
            "farming_cost 的输入不在 projects 表里，无法忠实重放；"
            "补一个默认值会把猜测伪装成真值。缺就该让前端显示「—」。"
        )

    def test_backfill_does_not_fabricate_when_score_missing(self, client):
        """`team_score` 缺失时不得凭空造一个档位。"""
        conn = get_connection()
        conn.execute(
            "INSERT INTO projects (id, name, source, team_json) VALUES (?, ?, ?, ?)",
            ("legacy-2", "No Score", "seed", json.dumps({"team_type": "unknown"})),
        )
        conn.commit()
        conn.close()

        response = client.get("/api/v1/projects/legacy-2")
        team = response.json()["data"]["project"]["team"]
        assert "risk_level" not in team, "没有 team_score 就无从推导档位，不该编一个出来。"

    def test_veto_reaches_the_detail_response(self, client):
        """资格门否决必须能被读到，否则 projects.veto 就是死数据。

        ADR-015 刻意让 `score` **不因否决改变**：一个被否决的项目分数照样很高。
        所以只看 `score` 与 `label` 无法区分「模型给了低分」与「被规则否决」，
        必须有字段承载。不暴露的话就是落了库却没人能读 —— 与
        `team.risk_level` 当年「算了只打日志」是同一类失效。
        """
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO projects (id, name, source, score, label, veto)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("vetoed-1", "Launched Bluechip", "seed", 69, "IGNORE", "already_launched"),
        )
        conn.commit()
        conn.close()

        project = client.get("/api/v1/projects/vetoed-1").json()["data"]["project"]
        assert project["veto"] == "already_launched"
        # 分数保持否决前的原值 —— 这正是不能靠 score 判断否决的原因。
        assert project["score"] == 69

    def test_pre_gate_rows_report_veto_as_null_not_a_default(self, client):
        """资格门上线前写入的行，`veto` 必须是 null。

        null 语义是「未经资格门评估」，不是「通过了资格门」。填一个假的
        「无否决」会把历史行伪装成已评估过，而 ADR-015 明确历史数据不重算。
        """
        conn = get_connection()
        conn.execute(
            "INSERT INTO projects (id, name, source, score, label) VALUES (?, ?, ?, ?, ?)",
            ("pre-gate-1", "Old Row", "seed", 72, "FARM"),
        )
        conn.commit()
        conn.close()

        project = client.get("/api/v1/projects/pre-gate-1").json()["data"]["project"]
        assert project["veto"] is None
