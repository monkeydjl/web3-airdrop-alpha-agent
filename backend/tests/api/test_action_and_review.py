"""今日行动队列 + 批量结果标记（闭环）的 API 测试。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    """使用临时数据库创建隔离的 TestClient。"""
    db_path = tmp_path / "action_review_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    app = create_app()
    return TestClient(app)


def _insert_project(
    pid: str,
    *,
    name: str,
    score: int,
    label: str,
    signals: dict | None = None,
) -> None:
    """插入一行项目：扩展信号写进 meta.signals（与生产存储形态一致）。"""
    meta = json.dumps(
        {
            "signals": signals
            if signals is not None
            else {"has_testnet": True, "has_task_portal": True, "has_docs": True}
        },
        ensure_ascii=False,
    )
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO projects
                (id, name, sector, stage, score, label, confidence, url, source, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (pid, name, "ZK", "testnet", score, label, 0.7, f"https://{pid}.example", "test", meta),
        )
        conn.commit()


class TestActionQueue:
    def test_empty_db_returns_empty_queue(self, client):
        res = client.get("/api/v1/action-queue")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["items"] == []
        assert data["summary"]["returned"] == 0

    def test_returns_actionable_tasks_for_farm_projects(self, client):
        _insert_project("p-farm", name="FarmOne", score=88, label="FARM")
        res = client.get("/api/v1/action-queue?limit=3")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["summary"]["returned"] >= 1
        item = data["items"][0]
        assert item["project_id"] == "p-farm"
        assert item["title"]
        assert item["rank_score"] > 0
        assert item["link"]

    def test_ignore_projects_never_appear(self, client):
        _insert_project("p-ignore", name="IgnoreMe", score=95, label="IGNORE")
        data = client.get("/api/v1/action-queue").json()["data"]
        assert data["items"] == []

    def test_engaged_projects_are_excluded_then_included_on_demand(self, client):
        _insert_project("p-a", name="Alpha", score=90, label="FARM")
        _insert_project("p-b", name="Beta", score=70, label="FARM")

        with get_connection() as conn:
            conn.execute(
                "INSERT INTO interactions (project_id, user_id, status) VALUES (?, ?, ?)",
                ("p-a", "default", "active"),
            )
            conn.commit()

        default_ids = {i["project_id"] for i in client.get("/api/v1/action-queue?limit=10").json()["data"]["items"]}
        assert default_ids == {"p-b"}

        with_engaged = client.get("/api/v1/action-queue?limit=10&include_engaged=true").json()["data"]
        assert {i["project_id"] for i in with_engaged["items"]} == {"p-a", "p-b"}
        assert with_engaged["summary"]["projects_skipped_engaged"] == 0

    def test_watchlisted_project_ranks_higher(self, client):
        _insert_project("p-plain", name="Plain", score=80, label="FARM")
        _insert_project("p-watched", name="Watched", score=80, label="FARM")
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO watchlist (project_id, user_id) VALUES (?, ?)",
                ("p-watched", "default"),
            )
            conn.commit()

        items = client.get("/api/v1/action-queue?limit=10").json()["data"]["items"]
        watched = next(i for i in items if i["project_id"] == "p-watched")
        plain = next(i for i in items if i["project_id"] == "p-plain")
        assert watched["watchlisted"] is True
        assert watched["rank_score"] > plain["rank_score"]

    def test_limit_is_enforced_and_spread_across_projects(self, client):
        for i in range(6):
            _insert_project(f"p{i}", name=f"P{i}", score=90 - i, label="FARM")
        data = client.get("/api/v1/action-queue?limit=4").json()["data"]
        assert len(data["items"]) == 4
        # 轮转取样：4 个名额应覆盖 4 个不同项目，而非被最高分项目占满
        assert data["summary"]["projects_in_queue"] == 4

    def test_invalid_limit_is_rejected(self, client):
        assert client.get("/api/v1/action-queue?limit=0").status_code == 422
        assert client.get("/api/v1/action-queue?limit=999").status_code == 422

    def test_candidate_pool_is_capped_regardless_of_db_size(self, client):
        """代价只与候选池上限相关，与库里项目总数无关。

        这是本端点不加缓存的依据：库涨到上万也只解析固定条数。
        插 120 个项目（> 候选池 60），考察的项目数必须停在 60。
        """
        from app.routers.v1.action_queue import _CANDIDATE_POOL

        for i in range(120):
            _insert_project(f"big{i:03d}", name=f"Big{i}", score=90 - (i % 40), label="FARM")

        data = client.get("/api/v1/action-queue?limit=5").json()["data"]
        assert data["summary"]["projects_considered"] <= _CANDIDATE_POOL
        assert data["summary"]["returned"] == 5

    def test_marked_project_is_excluded_on_next_request(self, client):
        """标记「已做」后该项目立刻从清单消失 —— 不加缓存才有这个即时性。

        注意 POST /interactions 不传 user_id 时落 NULL，而清单按默认用户查询，
        必须能读到 NULL 那批（见 tests/test_user_scope.py）。
        """
        _insert_project("p-mark", name="MarkMe", score=88, label="FARM")
        _insert_project("p-other", name="Other", score=70, label="FARM")

        first = client.get("/api/v1/action-queue?limit=10").json()["data"]
        assert "p-mark" in {i["project_id"] for i in first["items"]}

        res = client.post(
            "/api/v1/interactions",
            json={"project_id": "p-mark", "status": "active", "activities": "t", "outcome": "pending"},
        )
        assert res.status_code == 200

        after = client.get("/api/v1/action-queue?limit=10").json()["data"]
        assert "p-mark" not in {i["project_id"] for i in after["items"]}
        assert after["summary"]["projects_skipped_engaged"] == 1


class TestPendingReview:
    def test_lists_farm_and_watch_only(self, client):
        _insert_project("p-farm", name="F", score=80, label="FARM")
        _insert_project("p-watch", name="W", score=60, label="WATCH")
        _insert_project("p-ignore", name="I", score=90, label="IGNORE")

        data = client.get("/api/v1/feedback/pending-review?limit=50").json()["data"]
        ids = {i["project_id"] for i in data["items"]}
        assert ids == {"p-farm", "p-watch"}
        assert data["total_pending"] == 2

    def test_route_is_not_shadowed_by_project_id_route(self, client):
        """回归：动态路由 /feedback/{project_id} 若声明在前会吞掉本路由。"""
        data = client.get("/api/v1/feedback/pending-review").json()["data"]
        # 被吞掉时会返回 {"project_id": "pending-review", "count": 0, ...}
        assert "total_pending" in data
        assert "project_id" not in data

    def test_projects_with_interaction_rank_first(self, client):
        _insert_project("p-high", name="HighNoTouch", score=99, label="FARM")
        _insert_project("p-low", name="LowButTouched", score=40, label="FARM")
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO interactions (project_id, user_id, status) VALUES (?, ?, ?)",
                ("p-low", "default", "done"),
            )
            conn.commit()

        items = client.get("/api/v1/feedback/pending-review?limit=10").json()["data"]["items"]
        assert items[0]["project_id"] == "p-low"
        assert items[0]["has_interaction"] is True
        assert items[0]["priority_reason"] == "你有交互记录"


class TestFeedbackBatch:
    def test_batch_saves_and_removes_from_pending(self, client):
        for i in range(3):
            _insert_project(f"p{i}", name=f"P{i}", score=80, label="FARM")

        res = client.post(
            "/api/v1/feedback/batch",
            json={
                "items": [
                    {"project_id": "p0", "outcome": "airdropped"},
                    {"project_id": "p1", "outcome": "not_airdropped"},
                ]
            },
        )
        assert res.status_code == 200
        assert res.json()["data"]["saved"] == 2

        pending = client.get("/api/v1/feedback/pending-review?limit=50").json()["data"]
        assert {i["project_id"] for i in pending["items"]} == {"p2"}
        assert pending["already_marked"] == 2

    def test_batch_advances_calibration_progress(self, client):
        _insert_project("p0", name="P0", score=80, label="FARM")
        before = client.get("/api/v1/calibration/status").json()["data"]

        client.post(
            "/api/v1/feedback/batch",
            json={"items": [{"project_id": "p0", "outcome": "airdropped"}]},
        )

        after = client.get("/api/v1/calibration/status").json()["data"]
        assert after["total_feedback"] == before["total_feedback"] + 1
        assert after["strong_samples"] == before["strong_samples"] + 1
        assert after["samples_needed"] == before["samples_needed"] - 1
        # 门禁阈值不得被本功能改动（ADR/WEIGHT_CALIBRATION 约定）
        assert after["min_samples_gate"] == before["min_samples_gate"] == 200

    def test_empty_items_rejected(self, client):
        assert client.post("/api/v1/feedback/batch", json={"items": []}).status_code == 422

    def test_oversized_batch_rejected(self, client):
        """上限 50：本端点只需匿名 token，允许 200 条则一次请求即可填满校准门禁。"""
        items = [{"project_id": f"p{i}", "outcome": "airdropped"} for i in range(51)]
        assert client.post("/api/v1/feedback/batch", json={"items": items}).status_code == 422

    def test_unknown_project_id_is_rejected(self, client):
        """回归（安全）：伪造 project_id 不得入库。

        缺少存在性校验时，一次请求注入 200 条 ghost-N 就能让
        calibration_ready 变 True —— 用凭空数据决定真实评分权重（已实测）。
        """
        res = client.post(
            "/api/v1/feedback/batch",
            json={"items": [{"project_id": "ghost-1", "outcome": "airdropped"}]},
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] == "NOT_FOUND"
        # 且不得留下任何样本
        assert client.get("/api/v1/calibration/status").json()["data"]["total_feedback"] == 0

    def test_mixed_batch_rejects_whole_request(self, client):
        """一条伪造 ID 就整批拒绝，真实那条也不得写入。"""
        _insert_project("p-real", name="Real", score=80, label="FARM")
        res = client.post(
            "/api/v1/feedback/batch",
            json={
                "items": [
                    {"project_id": "p-real", "outcome": "airdropped"},
                    {"project_id": "ghost-2", "outcome": "airdropped"},
                ]
            },
        )
        assert res.status_code == 404
        assert client.get("/api/v1/calibration/status").json()["data"]["total_feedback"] == 0

    def test_not_found_is_not_masked_as_500(self, client):
        """404 不能被兜底 except 改写成 500（否则用户看到"服务器错误"）。"""
        res = client.post(
            "/api/v1/feedback/batch",
            json={"items": [{"project_id": "nope", "outcome": "dumped"}]},
        )
        assert res.status_code == 404
        assert res.json()["error"]["code"] != "DB_ERROR"

    def test_invalid_outcome_rejected(self, client):
        res = client.post(
            "/api/v1/feedback/batch",
            json={"items": [{"project_id": "p0", "outcome": "moon"}]},
        )
        assert res.status_code == 422

    def test_oversized_field_rejected_before_any_write(self, client):
        """超长字段被 pydantic 拦在入口，不产生任何写入。

        注意：这只证明"入口校验先于写入"，**不等于**证明事务回滚
        —— 真正的原子性由下面 test_write_failure_rolls_back_whole_batch 覆盖。
        """
        _insert_project("p0", name="P0", score=80, label="FARM")
        res = client.post(
            "/api/v1/feedback/batch",
            json={
                "items": [
                    {"project_id": "p0", "outcome": "airdropped"},
                    {"project_id": "x" * 65, "outcome": "airdropped"},
                ]
            },
        )
        assert res.status_code == 422
        assert client.get("/api/v1/calibration/status").json()["data"]["total_feedback"] == 0

    def test_write_failure_rolls_back_whole_batch(self, client, monkeypatch):
        """真正的原子性：写入过程中失败时，已插入的行必须回滚。

        构造方式：让 commit 抛错。若实现不是单事务 / 未回滚，
        前面 executemany 插入的行会残留下来。
        """
        for i in range(3):
            _insert_project(f"p{i}", name=f"P{i}", score=80, label="FARM")

        import app.routers.v1.feedback as fb

        real_get_connection = fb.get_connection

        class _FailingCommitConn:
            """代理真实连接，但 commit 时抛错。"""

            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def commit(self):
                raise RuntimeError("simulated commit failure")

        class _Ctx:
            def __enter__(self):
                self._cm = real_get_connection()
                return _FailingCommitConn(self._cm.__enter__())

            def __exit__(self, *exc):
                return self._cm.__exit__(*exc)

        monkeypatch.setattr(fb, "get_connection", lambda: _Ctx())

        res = client.post(
            "/api/v1/feedback/batch",
            json={
                "items": [
                    {"project_id": "p0", "outcome": "airdropped"},
                    {"project_id": "p1", "outcome": "not_airdropped"},
                ]
            },
        )
        assert res.status_code == 500

        # 关键断言：失败后一条都不该留下
        monkeypatch.undo()
        assert client.get("/api/v1/calibration/status").json()["data"]["total_feedback"] == 0
