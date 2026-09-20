"""Tests for the project skip (「不参与」) endpoints.

- POST /projects/{id}/skip 标记，幂等
- DELETE /projects/{id}/skip 取消
- GET /projects 列表响应带 skipped 标记（供工作台默认隐藏）
请求以默认匿名用户隔离（与 watchlist 同一口径）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentContext, PipelineState, RawProject
from app.main import create_app
from app.repository import ProjectRepository


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture(autouse=True)
def clean_skips():
    from app.db import get_connection

    with get_connection() as conn:
        conn.execute("DELETE FROM project_skips")
        conn.commit()
    yield


def _save_project(repo: ProjectRepository, pid: str, name: str) -> None:
    repo.save(
        PipelineState(
            project=RawProject(
                id=pid,
                name=name,
                url=f"https://{pid}.example.com",
                sector="DeFi",
                stage="testnet",
                source="test",
                no_token_yet=True,
                created_at=None,
            ),
            context=AgentContext(run_id="r1"),
            score=66,
            label="WATCH",
            confidence=0.6,
            reason=[],
        )
    )


class TestSkipEndpoints:
    def test_skip_unknown_project_404(self, client):
        r = client.post("/api/v1/projects/no-such/skip")
        assert r.status_code == 404

    def test_skip_and_list_flag_roundtrip(self, client):
        repo = ProjectRepository()
        _save_project(repo, "skip-a", "Alpha")
        _save_project(repo, "skip-b", "Beta")

        r = client.post("/api/v1/projects/skip-a/skip")
        assert r.status_code == 200
        assert r.json()["data"]["skipped"] is True

        # 列表响应带 skipped 标记：Alpha 被打上，Beta 没有
        lst = client.get("/api/v1/projects?page_size=50")
        assert lst.status_code == 200
        rows = {p["id"]: p for p in lst.json()["data"]["projects"]}
        assert rows["skip-a"]["skipped"] is True
        assert rows["skip-b"]["skipped"] is False

    def test_skip_is_idempotent(self, client):
        repo = ProjectRepository()
        _save_project(repo, "skip-c", "Gamma")

        client.post("/api/v1/projects/skip-c/skip")
        r = client.post("/api/v1/projects/skip-c/skip")
        assert r.status_code == 200  # 重复点击不报错、不产生多行
        assert r.json()["data"]["already"] is True

        from app.db import get_connection

        with get_connection() as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM project_skips WHERE project_id='skip-c'"
            ).fetchone()[0]
        assert n == 1

    def test_unskip_roundtrip(self, client):
        repo = ProjectRepository()
        _save_project(repo, "skip-d", "Delta")

        client.post("/api/v1/projects/skip-d/skip")
        r = client.delete("/api/v1/projects/skip-d/skip")
        assert r.status_code == 200
        assert r.json()["data"]["skipped"] is False

        lst = client.get("/api/v1/projects?page_size=50")
        rows = {p["id"]: p for p in lst.json()["data"]["projects"]}
        assert rows["skip-d"]["skipped"] is False

    def test_unskip_when_not_skipped_is_404(self, client):
        repo = ProjectRepository()
        _save_project(repo, "skip-e", "Epsilon")
        r = client.delete("/api/v1/projects/skip-e/skip")
        assert r.status_code == 404

    def test_skips_are_per_user_isolated(self, client):
        """默认用户之外的用户传 user_id 不应看到 default 的跳过。"""
        repo = ProjectRepository()
        _save_project(repo, "skip-f", "Foxtrot")
        client.post("/api/v1/projects/skip-f/skip")
        r = client.get("/api/v1/projects?user_id=alice&page_size=50")
        rows = {p["id"]: p for p in r.json()["data"]["projects"]}
        assert rows["skip-f"]["skipped"] is False, "跳过标记应按用户隔离"
