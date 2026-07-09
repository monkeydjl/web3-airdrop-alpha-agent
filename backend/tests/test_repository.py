"""Tests for Repository Layer.

Reference:
- backend/app/repository.py
- backend/app/db.py
"""

import pytest
import json
from datetime import datetime, timezone

from app.db import get_connection, init_db
from app.repository import ProjectRepository, LogRepository
from app.agents.base import RawProject, PipelineState, AgentContext
from app.models import NarrativeResult, TeamResult, RiskResult, TokenomicsResult


@pytest.fixture
def db_conn():
    """Test database connection fixture."""
    conn = get_connection()
    # Use in-memory database for tests
    conn.close()

    # Create in-memory database
    import sqlite3
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row

    # Initialize schema
    init_db(conn)

    yield conn
    conn.close()


@pytest.fixture
def sample_state():
    """Sample pipeline state fixture."""
    project = RawProject(
        id="test-001",
        name="Test Project",
        url="https://test.xyz",
        sector="L2",
        stage="testnet",
        source="test",
    )

    context = AgentContext(
        run_id="test-run-001",
        enable_llm=False,
    )

    state = PipelineState(project=project, context=context)

    # Add analysis results
    state.narrative = NarrativeResult(
        sector="L2",
        stage="growth",
        heat_score=0.9,
        timing="early",
    )

    state.team = TeamResult(
        team_score=0.8,
        team_flags=["tier-1 backed"],
        team_type="semi_anon",
    )

    state.risk = RiskResult(
        token_risk=0.3,
        risk_flags=[],
        unlock_pressure="medium",
    )

    state.tokenomics = TokenomicsResult(
        vc_share=0.3,
        team_share=0.25,
        unlock_penalty=0.35,
    )

    # Add scoring results
    state.score = 85
    state.label = "FARM"
    state.confidence = 1.0
    state.reason = ["strong signal", "early timing"]

    return state


class TestProjectRepository:
    """Test ProjectRepository."""

    def test_save_project(self, db_conn, sample_state):
        """Test saving a project."""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        # Verify saved
        cursor = db_conn.execute(
            "SELECT * FROM projects WHERE id = ?",
            (sample_state.project.id,)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["name"] == "Test Project"
        assert row["sector"] == "L2"
        assert row["score"] == 85
        assert row["label"] == "FARM"

    def test_save_project_with_json_fields(self, db_conn, sample_state):
        """Test that JSON fields are properly serialized."""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        cursor = db_conn.execute(
            "SELECT narrative_json, team_json FROM projects WHERE id = ?",
            (sample_state.project.id,)
        )
        row = cursor.fetchone()

        # Verify JSON serialization
        narrative = json.loads(row["narrative_json"])
        assert narrative["sector"] == "L2"
        assert narrative["heat_score"] == 0.9

        team = json.loads(row["team_json"])
        assert team["team_score"] == 0.8

    def test_save_replaces_existing(self, db_conn, sample_state):
        """Test that saving updates existing project."""
        repo = ProjectRepository(db_conn)

        # First save
        repo.save(sample_state)

        # Update and save again
        sample_state.score = 90
        sample_state.label = "WATCH"
        repo.save(sample_state)

        # Verify updated
        cursor = db_conn.execute(
            "SELECT score, label FROM projects WHERE id = ?",
            (sample_state.project.id,)
        )
        row = cursor.fetchone()

        assert row["score"] == 90
        assert row["label"] == "WATCH"

    def test_save_batch(self, db_conn, sample_state):
        """Test batch saving projects."""
        repo = ProjectRepository(db_conn)

        # Create multiple states
        states = []
        for i in range(3):
            project = RawProject(
                id=f"test-{i:03d}",
                name=f"Project {i}",
                sector="L2",
                source="test",
            )
            context = AgentContext(run_id="test-run", enable_llm=False)
            state = PipelineState(project=project, context=context)
            state.score = 80 + i
            state.label = "FARM"
            state.confidence = 1.0
            state.reason = ["test"]
            states.append(state)

        # Save batch
        saved = repo.save_batch(states)
        assert saved == 3

        # Verify all saved
        cursor = db_conn.execute("SELECT COUNT(*) FROM projects")
        count = cursor.fetchone()[0]
        assert count == 3

    def test_get_by_id(self, db_conn, sample_state):
        """Test getting project by ID."""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        # Get by ID
        project = repo.get_by_id(sample_state.project.id)

        assert project is not None
        assert project["name"] == "Test Project"
        assert project["score"] == 85

    def test_get_by_id_not_found(self, db_conn):
        """Test getting non-existent project."""
        repo = ProjectRepository(db_conn)
        project = repo.get_by_id("nonexistent")
        assert project is None

    def test_list_projects_empty(self, db_conn):
        """Test listing projects when empty."""
        repo = ProjectRepository(db_conn)
        projects, total = repo.list_projects()

        assert projects == []
        assert total == 0

    def test_list_projects_with_data(self, db_conn, sample_state):
        """Test listing projects with data."""
        repo = ProjectRepository(db_conn)

        # Save multiple projects
        for i in range(5):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.project.name = f"Project {i}"
            state.score = 80 + i
            repo.save(state)

        # List all
        projects, total = repo.list_projects(page=1, page_size=10)

        assert len(projects) == 5
        assert total == 5

    def test_list_projects_pagination(self, db_conn, sample_state):
        """Test pagination."""
        repo = ProjectRepository(db_conn)

        # Save 10 projects
        for i in range(10):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.score = 80 + i
            repo.save(state)

        # Get page 1
        projects, total = repo.list_projects(page=1, page_size=5)
        assert len(projects) == 5
        assert total == 10

        # Get page 2
        projects, total = repo.list_projects(page=2, page_size=5)
        assert len(projects) == 5
        assert total == 10

    def test_list_projects_filter_by_label(self, db_conn, sample_state):
        """Test filtering by label."""
        repo = ProjectRepository(db_conn)

        # Save projects with different labels
        for i, label in enumerate(["FARM", "WATCH", "FARM", "IGNORE"]):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.label = label
            repo.save(state)

        # Filter by FARM
        projects, total = repo.list_projects(label="FARM")
        assert len(projects) == 2
        assert total == 2

    def test_list_projects_filter_by_sector(self, db_conn, sample_state):
        """Test filtering by sector."""
        repo = ProjectRepository(db_conn)

        # Save projects in different sectors
        for i, sector in enumerate(["L2", "DeFi", "L2", "Gaming"]):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.project.sector = sector
            repo.save(state)

        # Filter by L2
        projects, total = repo.list_projects(sector="L2")
        assert len(projects) == 2
        assert total == 2

    def test_list_projects_filter_by_min_score(self, db_conn, sample_state):
        """Test filtering by minimum score."""
        repo = ProjectRepository(db_conn)

        # Save projects with different scores
        for i, score in enumerate([70, 80, 85, 90]):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.score = score
            repo.save(state)

        # Filter min_score=80
        projects, total = repo.list_projects(min_score=80)
        assert len(projects) == 3
        assert total == 3

    def test_list_projects_sort_by_score_desc(self, db_conn, sample_state):
        """Test sorting by score descending."""
        repo = ProjectRepository(db_conn)

        # Save projects with different scores
        for i, score in enumerate([70, 90, 80]):
            state = sample_state
            state.project.id = f"test-{i:03d}"
            state.score = score
            repo.save(state)

        # Sort by score desc
        projects, total = repo.list_projects(sort_by="score", sort_order="desc")

        assert projects[0]["score"] == 90
        assert projects[1]["score"] == 80
        assert projects[2]["score"] == 70

    def test_list_projects_sort_by_name_asc(self, db_conn, sample_state):
        """Test sorting by name ascending."""
        repo = ProjectRepository(db_conn)

        # Save projects with different names
        for name in ["Charlie", "Alice", "Bob"]:
            state = sample_state
            state.project.id = name.lower()
            state.project.name = name
            repo.save(state)

        # Sort by name asc
        projects, total = repo.list_projects(sort_by="name", sort_order="asc")

        assert projects[0]["name"] == "Alice"
        assert projects[1]["name"] == "Bob"
        assert projects[2]["name"] == "Charlie"

    def test_delete_by_id(self, db_conn, sample_state):
        """Test deleting project."""
        repo = ProjectRepository(db_conn)
        repo.save(sample_state)

        # Delete
        deleted = repo.delete_by_id(sample_state.project.id)
        assert deleted is True

        # Verify deleted
        project = repo.get_by_id(sample_state.project.id)
        assert project is None

    def test_delete_by_id_not_found(self, db_conn):
        """Test deleting non-existent project."""
        repo = ProjectRepository(db_conn)
        deleted = repo.delete_by_id("nonexistent")
        assert deleted is False


class TestLogRepository:
    """Test LogRepository."""

    def test_log_run(self, db_conn):
        """Test logging a run."""
        repo = LogRepository(db_conn)

        repo.log_run(
            run_id="test-run-001",
            project_id="test-project-001",
            agent_name="narrative",
            input_data={"project": "test"},
            output_data={"heat_score": 0.9},
            duration_ms=100,
        )

        # Verify logged
        cursor = db_conn.execute(
            "SELECT * FROM logs WHERE run_id = ?",
            ("test-run-001",)
        )
        row = cursor.fetchone()

        assert row is not None
        assert row["agent_name"] == "narrative"
        assert row["duration_ms"] == 100

    def test_log_run_with_error(self, db_conn):
        """Test logging run with error."""
        repo = LogRepository(db_conn)

        repo.log_run(
            run_id="test-run-002",
            project_id="test-project-001",
            agent_name="team",
            error="Test error",
        )

        # Verify logged
        cursor = db_conn.execute(
            "SELECT error FROM logs WHERE run_id = ?",
            ("test-run-002",)
        )
        row = cursor.fetchone()

        assert row["error"] == "Test error"

    def test_get_run_logs(self, db_conn):
        """Test getting logs for a run."""
        repo = LogRepository(db_conn)

        # Log multiple entries
        for i in range(3):
            repo.log_run(
                run_id="test-run-003",
                agent_name=f"agent-{i}",
            )

        # Get logs
        logs = repo.get_run_logs("test-run-003")

        assert len(logs) == 3
        assert logs[0]["agent_name"] == "agent-0"

    def test_get_run_logs_empty(self, db_conn):
        """Test getting logs for non-existent run."""
        repo = LogRepository(db_conn)
        logs = repo.get_run_logs("nonexistent")
        assert logs == []
