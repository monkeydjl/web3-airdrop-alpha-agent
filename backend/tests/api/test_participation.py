"""参与流水（F2，ACTION_LOOP_DESIGN §3）测试：状态机 / 隔离 / 级联。

身份边界是本组测试的重点之一：user_id 来自 token（`get_current_user`），
**不接受请求体自报** —— 2026-08-30 审核 P1-1 的同款教训。跨 token 的
正反断言都要有：只验证"自己的能看到"是半个断言。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import create_app

ADMIN_HEADERS = {"X-API-Key": "test-admin-key-participation-000"}


@pytest.fixture
def client(tmp_path):
    db_path = tmp_path / "test.db"
    prev_db_path = settings.db_path
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    yield TestClient(app)
    settings.db_path = prev_db_path


@pytest.fixture
def authed(client):
    """开启鉴权 + 一个已 seed 的项目，返回 (client, token_a, token_b)。"""
    prev_key = settings.api_key
    settings.api_key = ADMIN_HEADERS["X-API-Key"]
    try:
        _seed_project()
        tokens = []
        for _ in range(2):
            r = client.post("/api/v1/auth/anonymous")
            assert r.status_code == 200
            tokens.append(r.json()["access_token"])
        yield client, tokens[0], tokens[1]
    finally:
        settings.api_key = prev_key


def _seed_project() -> None:
    """种子项目：直接走管理员 /run 会触发完整评分（重），手工 INSERT 更精准。"""
    from datetime import UTC, datetime

    from app.db import get_connection

    with get_connection() as conn:
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO projects (id, name, score, label, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            ("proj-1", "Test Project", 70, "FARM", now, now),
        )
        conn.commit()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


class TestCreatePlan:
    def test_create_with_generated_seed(self, authed):
        client, token_a, _ = authed
        r = client.post(
            "/api/v1/projects/proj-1/participation",
            json={"seed_from_generated": True},
            headers=_auth(token_a),
        )
        assert r.status_code == 200, r.text
        data = r.json()["data"]
        assert data["project_id"] == "proj-1"
        assert data["seeded_tasks"] > 0

        listed = client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["items"]
        assert len(listed) == 1
        assert listed[0]["status"] == "active"
        assert len(listed[0]["tasks"]) == data["seeded_tasks"]

    def test_duplicate_plan_returns_409(self, authed):
        client, token_a, _ = authed
        for _ in range(2):
            r = client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "ALREADY_EXISTS"

    def test_unknown_project_returns_404(self, authed):
        client, token_a, _ = authed
        r = client.post("/api/v1/projects/nope/participation", json={}, headers=_auth(token_a))
        assert r.status_code == 404

    def test_body_user_id_is_not_honored(self, authed):
        """请求体里的 user_id 必须被忽略 —— 身份只来自 token。"""
        client, token_a, token_b = authed
        r = client.post(
            "/api/v1/projects/proj-1/participation",
            json={"user_id": "anon-spoofed"},
            headers=_auth(token_a),
        )
        assert r.status_code == 200
        # token_b 看不到 token_a 的 plan（body 自报身份没有被采纳）
        listed = client.get("/api/v1/participation", headers=_auth(token_b)).json()["data"]
        assert listed["count"] == 0


class TestIsolation:
    def test_plans_are_isolated_by_token(self, authed):
        client, token_a, token_b = authed
        assert client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a)).status_code == 200
        assert client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["count"] == 1
        assert client.get("/api/v1/participation", headers=_auth(token_b)).json()["data"]["count"] == 0

    def test_foreign_plan_reads_as_404(self, authed):
        """跨 token 的 plan/任务一律 404 —— 不向试探者确认存在性。"""
        client, token_a, token_b = authed
        client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        listed = client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["items"]
        plan_id = listed[0]["id"]
        task_id = listed[0]["tasks"][0]["id"]

        assert (
            client.patch(
                f"/api/v1/participation/{plan_id}", json={"status": "paused"}, headers=_auth(token_b)
            ).status_code
            == 404
        )
        assert (
            client.patch(
                f"/api/v1/participation/tasks/{task_id}", json={"status": "done"}, headers=_auth(token_b)
            ).status_code
            == 404
        )
        assert client.delete(f"/api/v1/participation/{plan_id}", headers=_auth(token_b)).status_code == 404


class TestStateMachine:
    @pytest.fixture
    def ids(self, authed):
        client, token_a, _ = authed
        client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        plan = client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["items"][0]
        return client, token_a, plan["id"], plan["tasks"][0]["id"]

    def test_plan_valid_transition(self, ids):
        client, token, plan_id, _ = ids
        r = client.patch(f"/api/v1/participation/{plan_id}", json={"status": "paused"}, headers=_auth(token))
        assert r.status_code == 200
        listed = client.get("/api/v1/participation?status=paused", headers=_auth(token)).json()["data"]
        assert listed["count"] == 1

    def test_plan_invalid_transition_422(self, ids):
        client, token, plan_id, _ = ids
        r = client.patch(f"/api/v1/participation/{plan_id}", json={"status": "abandoned"}, headers=_auth(token))
        assert r.status_code == 200
        # abandoned → paused 不在闭表里
        r = client.patch(f"/api/v1/participation/{plan_id}", json={"status": "paused"}, headers=_auth(token))
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "INVALID_TRANSITION"

    def test_task_done_records_completed_at(self, ids):
        client, token, _, task_id = ids
        r = client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "doing"}, headers=_auth(token))
        assert r.status_code == 200
        r = client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "done"}, headers=_auth(token))
        assert r.status_code == 200
        plan = client.get("/api/v1/participation", headers=_auth(token)).json()["data"]["items"][0]
        task = next(t for t in plan["tasks"] if t["id"] == task_id)
        assert task["status"] == "done"
        assert task["completed_at"] is not None

    def test_task_reopen_clears_completed_at(self, ids):
        client, token, _, task_id = ids
        client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "done"}, headers=_auth(token))
        client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "todo"}, headers=_auth(token))
        plan = client.get("/api/v1/participation", headers=_auth(token)).json()["data"]["items"][0]
        task = next(t for t in plan["tasks"] if t["id"] == task_id)
        assert task["status"] == "todo"
        assert task["completed_at"] is None

    def test_task_invalid_transition_422(self, ids):
        client, token, _, task_id = ids
        # todo → skipped 合法，但 skipped → doing 不在闭表里
        client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "skipped"}, headers=_auth(token))
        r = client.patch(f"/api/v1/participation/tasks/{task_id}", json={"status": "doing"}, headers=_auth(token))
        assert r.status_code == 422


class TestDelete:
    def test_delete_plan_cascades_tasks(self, authed):
        client, token_a, _ = authed
        client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        plan = client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["items"][0]
        assert plan["tasks"], "seed 后应有任务"

        r = client.delete(f"/api/v1/participation/{plan['id']}", headers=_auth(token_a))
        assert r.status_code == 200
        assert client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["count"] == 0

        # 重新创建 + seed：任务不该从旧 plan 复活（级联删除生效）
        client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        plan2 = client.get("/api/v1/participation", headers=_auth(token_a)).json()["data"]["items"][0]
        assert len(plan2["tasks"]) == len(plan["tasks"])


class TestAuthModes:
    def test_anonymous_token_writable_when_auth_enabled(self, authed):
        client, token_a, _ = authed
        r = client.post("/api/v1/projects/proj-1/participation", json={}, headers=_auth(token_a))
        assert r.status_code == 200

    def test_open_mode_still_works(self, client):
        """MVP 模式（API_KEY 空）：无 token 也可用，统一记为 anonymous。"""
        _seed_project()
        client.post("/api/v1/projects/proj-1/participation", json={})
        r = client.get("/api/v1/participation")
        assert r.status_code == 200
        assert r.json()["data"]["count"] == 1
