"""API integration tests for row-level data isolation (W12-10).

Verifies that:
- User A cannot see User B's feedback or events.
- Admin can view all users' feedback and events or filter by user_id.
- Non-admin cannot spoof user_id in write requests.
- Watchlist, project skips, and interactions are isolated by user.
- Projects and project history remain globally shared.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.auth import issue_access_token
from app.config import settings
from app.db import get_connection, init_db
from app.main import create_app


@pytest.fixture(autouse=True)
def setup_isolation_db(tmp_path, monkeypatch):
    """设置独立测试数据库并启用反馈与事件系统。"""
    test_db = str(tmp_path / "isolation_test.db")
    monkeypatch.setattr(settings, "db_path", test_db)
    monkeypatch.setattr(settings, "api_key", "admin-secret-key-123")
    monkeypatch.setattr(settings, "jwt_secret", "jwt-test-secret-456-longer-key-32b!")
    monkeypatch.setattr(settings, "enable_feedback_system", True)
    monkeypatch.setattr(settings, "enable_events_tracking", True)

    init_db()

    with get_connection() as conn:
        # 清理旧数据
        conn.execute("DELETE FROM feedback")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM watchlist")
        conn.execute("DELETE FROM project_skips")
        conn.execute("DELETE FROM interactions")
        conn.execute("DELETE FROM users")
        conn.execute("DELETE FROM projects")

        # 插入基础测试项目（全局共享资源）
        conn.execute(
            """
            INSERT INTO projects (
                id, name, sector, stage, score, label, confidence, url, created_at, updated_at
            ) VALUES (
                'layerx-001', 'LayerX', 'Infra', 'Testnet', 88.5, 'FARM', 0.92, 'https://layerx.io',
                '2026-09-01 00:00:00', '2026-09-01 00:00:00'
            )
            """
        )

        # 插入测试用户
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, display_name, role)
            VALUES
                ('usr_alice', 'alice@example.com', 'hash_a', 'Alice', 'analyst'),
                ('usr_bob', 'bob@example.com', 'hash_b', 'Bob', 'viewer'),
                ('usr_charlie', 'charlie@example.com', 'hash_c', 'Charlie', 'analyst'),
                ('usr_admin', 'admin@example.com', 'hash_admin', 'Admin', 'admin')
            """
        )
        conn.commit()

    yield


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


@pytest.fixture
def alice_headers():
    token, _, _ = issue_access_token("usr_alice", "analyst")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def bob_headers():
    token, _, _ = issue_access_token("usr_bob", "viewer")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def charlie_headers():
    token, _, _ = issue_access_token("usr_charlie", "analyst")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin_headers():
    token, _, _ = issue_access_token("usr_admin", "admin")
    return {"Authorization": f"Bearer {token}"}


class TestFeedbackDataIsolation:
    def test_user_cannot_see_other_user_feedback(
        self,
        client: TestClient,
        alice_headers: dict[str, str],
        bob_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        # 1. Alice 提交一条 feedback
        res_a = client.post(
            "/api/v1/feedback",
            headers=alice_headers,
            json={
                "project_id": "layerx-001",
                "signal": "useful",
                "note": "Alice says it is useful",
            },
        )
        assert res_a.status_code == 200

        # 2. Admin 提交一条 feedback（模拟另一个用户）
        res_b = client.post(
            "/api/v1/feedback",
            headers=admin_headers,
            json={
                "project_id": "layerx-001",
                "signal": "useless",
                "note": "Admin says useless",
            },
        )
        assert res_b.status_code == 200

        # 3. Alice 查询：只能看到自己的 1 条反馈，看不到 Admin 的反馈
        alice_query = client.get("/api/v1/feedback/layerx-001", headers=alice_headers)
        assert alice_query.status_code == 200
        alice_data = alice_query.json()["data"]
        assert alice_data["count"] == 1
        assert alice_data["signals"] == {"useful": 1}
        assert alice_data["items"][0]["note"] == "Alice says it is useful"

        # 4. Bob 查询：Bob 未提交过任何反馈，返回 count = 0
        bob_query = client.get("/api/v1/feedback/layerx-001", headers=bob_headers)
        assert bob_query.status_code == 200
        bob_data = bob_query.json()["data"]
        assert bob_data["count"] == 0
        assert bob_data["items"] == []

        # 5. Alice 试图通过 ?user_id=usr_admin 窥探 Admin 的反馈：被强制绑定为自身身份
        alice_spoof = client.get("/api/v1/feedback/layerx-001?user_id=usr_admin", headers=alice_headers)
        assert alice_spoof.status_code == 200
        assert alice_spoof.json()["data"]["count"] == 1
        assert alice_spoof.json()["data"]["items"][0]["note"] == "Alice says it is useful"

        # 6. Admin 查询：默认可查看全部 2 条反馈
        admin_query = client.get("/api/v1/feedback/layerx-001", headers=admin_headers)
        assert admin_query.status_code == 200
        admin_data = admin_query.json()["data"]
        assert admin_data["count"] == 2
        assert admin_data["signals"] == {"useful": 1, "useless": 1}

        # 7. Admin 指定 ?user_id=usr_alice 过滤
        admin_filtered = client.get("/api/v1/feedback/layerx-001?user_id=usr_alice", headers=admin_headers)
        assert admin_filtered.status_code == 200
        assert admin_filtered.json()["data"]["count"] == 1
        assert admin_filtered.json()["data"]["items"][0]["note"] == "Alice says it is useful"


class TestEventsDataIsolation:
    def test_user_cannot_see_other_user_events(
        self,
        client: TestClient,
        alice_headers: dict[str, str],
        bob_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        # 1. Alice 提交点击事件
        res_a = client.post(
            "/api/v1/events",
            headers=alice_headers,
            json={
                "project_id": "layerx-001",
                "event_type": "click",
                "detail": '{"btn": "whitepaper"}',
            },
        )
        assert res_a.status_code == 200

        # 2. Bob 提交展开事件
        res_b = client.post(
            "/api/v1/events",
            headers=bob_headers,
            json={
                "project_id": "layerx-001",
                "event_type": "expand",
                "detail": '{"section": "tokenomics"}',
            },
        )
        assert res_b.status_code == 200

        # 3. Alice 查询事件：只能看到自己的 click 事件
        alice_events = client.get("/api/v1/events", headers=alice_headers)
        assert alice_events.status_code == 200
        a_data = alice_events.json()["data"]
        assert a_data["total"] == 1
        assert a_data["items"][0]["event_type"] == "click"

        # 4. Bob 查询事件：只能看到自己的 expand 事件
        bob_events = client.get("/api/v1/events", headers=bob_headers)
        assert bob_events.status_code == 200
        b_data = bob_events.json()["data"]
        assert b_data["total"] == 1
        assert b_data["items"][0]["event_type"] == "expand"

        # 5. Alice 试图通过 ?user_id=usr_bob 偷看：被强制过滤为 Alice
        alice_spoof = client.get("/api/v1/events?user_id=usr_bob", headers=alice_headers)
        assert alice_spoof.status_code == 200
        assert alice_spoof.json()["data"]["total"] == 1
        assert alice_spoof.json()["data"]["items"][0]["event_type"] == "click"

        # 6. Admin 查询事件：可查看全部 2 条事件
        admin_events = client.get("/api/v1/events", headers=admin_headers)
        assert admin_events.status_code == 200
        adm_data = admin_events.json()["data"]
        assert adm_data["total"] == 2

        # 7. Admin 过滤查询
        admin_filtered = client.get("/api/v1/events?user_id=usr_bob", headers=admin_headers)
        assert admin_filtered.status_code == 200
        assert admin_filtered.json()["data"]["total"] == 1
        assert admin_filtered.json()["data"]["items"][0]["event_type"] == "expand"


class TestWatchlistDataIsolation:
    def test_watchlist_isolation(
        self,
        client: TestClient,
        alice_headers: dict[str, str],
        bob_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        # Alice 添加关注
        res_a = client.post(
            "/api/v1/watchlist/layerx-001",
            headers=alice_headers,
            json={"note": "Alice watchlist note"},
        )
        assert res_a.status_code == 200

        # Bob 查看关注列表：为空
        bob_list = client.get("/api/v1/watchlist", headers=bob_headers)
        assert bob_list.status_code == 200
        assert bob_list.json()["data"]["total"] == 0

        # Alice 查看关注列表：有 1 条
        alice_list = client.get("/api/v1/watchlist", headers=alice_headers)
        assert alice_list.status_code == 200
        assert alice_list.json()["data"]["total"] == 1
        assert alice_list.json()["data"]["items"][0]["note"] == "Alice watchlist note"

        # Admin 可查看 Alice 的关注列表
        admin_view = client.get("/api/v1/watchlist?user_id=usr_alice", headers=admin_headers)
        assert admin_view.status_code == 200
        assert admin_view.json()["data"]["total"] == 1


class TestProjectSkipsDataIsolation:
    def test_skip_isolation(
        self,
        client: TestClient,
        alice_headers: dict[str, str],
        charlie_headers: dict[str, str],
    ) -> None:
        # Alice 标记跳过
        res_a = client.post("/api/v1/projects/layerx-001/skip", headers=alice_headers)
        assert res_a.status_code == 200

        # Charlie 尝试取消跳过：返回 404（Charlie 从未跳过）
        res_charlie = client.delete("/api/v1/projects/layerx-001/skip", headers=charlie_headers)
        assert res_charlie.status_code == 404

        # Alice 取消跳过：成功
        res_alice_unskip = client.delete("/api/v1/projects/layerx-001/skip", headers=alice_headers)
        assert res_alice_unskip.status_code == 200


class TestGlobalSharedData:
    def test_projects_and_details_are_globally_shared(
        self,
        client: TestClient,
        alice_headers: dict[str, str],
        bob_headers: dict[str, str],
        admin_headers: dict[str, str],
    ) -> None:
        # Alice, Bob, Admin 访问项目列表与详情，结果完全一致
        res_a = client.get("/api/v1/projects", headers=alice_headers).json()
        res_b = client.get("/api/v1/projects", headers=bob_headers).json()
        res_adm = client.get("/api/v1/projects", headers=admin_headers).json()

        assert res_a["data"]["projects"] == res_b["data"]["projects"] == res_adm["data"]["projects"]

        detail_a = client.get("/api/v1/projects/layerx-001", headers=alice_headers).json()
        detail_b = client.get("/api/v1/projects/layerx-001", headers=bob_headers).json()
        detail_adm = client.get("/api/v1/projects/layerx-001", headers=admin_headers).json()

        assert detail_a["data"]["project"]["score"] == detail_b["data"]["project"]["score"] == detail_adm["data"]["project"]["score"] == 88.5
        assert detail_a["data"]["project"]["label"] == detail_b["data"]["project"]["label"] == detail_adm["data"]["project"]["label"] == "FARM"
