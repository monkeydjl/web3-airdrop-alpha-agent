"""归档运行历史 API（GET /api/v1/archive/runs）的测试。

这个端点解决的是一个具体的诚实占位：前端 `/archive` 页此前只能显示
"暂无运行历史接口" —— 归档逻辑是真的，但没有调度、没有运行记录、
没有查询接口。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.archive import RawDataArchiver
from app.config import settings
from app.db import get_connection
from app.main import create_app
from app.repositories.archive_runs import (
    STATUS_FAILED,
    TRIGGER_API,
    TRIGGER_MANUAL,
    TRIGGER_SCHEDULER,
    ArchiveRunRepository,
)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "archive_api.db"))
    return TestClient(create_app())


def _insert_raw(discovered_at: datetime, *, processed: int = 1) -> str:
    raw_id = f"raw-{discovered_at.timestamp()}-{processed}"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO raw_projects (
                raw_id, source_id, dedup_key, raw_data, discovered_at,
                processed, processed_at, project_id, discovery_score
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_id,
                "defillama",
                f"dedup-{raw_id}",
                '{"name": "X"}',
                discovered_at.isoformat(),
                processed,
                discovered_at.isoformat() if processed else None,
                f"proj-{raw_id}",
                0.5 if processed else 0.1,
            ),
        )
        conn.commit()
    return raw_id


class TestArchiveRunsEndpoint:
    def test_empty_history_is_honest_not_broken(self, client):
        """一次都没跑过时返回空列表，而不是 500，也不是编个假记录。"""
        res = client.get("/api/v1/archive/runs")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["runs"] == []
        assert data["summary"]["total_runs"] == 0
        assert data["summary"]["last_run_at"] is None

    def test_reports_real_run(self, client):
        _insert_raw(datetime.now(UTC) - timedelta(days=40), processed=1)
        with get_connection() as conn:
            RawDataArchiver(raw_retention_days=30, dry_run=False).run_and_record(conn, trigger=TRIGGER_MANUAL)

        data = client.get("/api/v1/archive/runs").json()["data"]
        assert data["summary"]["total_runs"] == 1
        assert data["summary"]["failed_runs"] == 0
        assert data["summary"]["last_run_at"] is not None
        run = data["runs"][0]
        assert run["trigger"] == TRIGGER_MANUAL
        assert run["raw_archived"] == 1
        assert run["duration_ms"] >= 0

    def test_failed_run_is_visible(self, client):
        """失败的运行必须出现在历史里 —— 只显示成功会给人虚假的安心。"""
        with get_connection() as conn:
            ArchiveRunRepository(conn).record(
                started_at=datetime.now(UTC),
                trigger=TRIGGER_SCHEDULER,
                status=STATUS_FAILED,
                error_message="disk full",
            )

        data = client.get("/api/v1/archive/runs").json()["data"]
        assert data["summary"]["failed_runs"] == 1
        assert data["runs"][0]["error_message"] == "disk full"

    def test_runs_are_newest_first(self, client):
        base = datetime.now(UTC)
        with get_connection() as conn:
            repo = ArchiveRunRepository(conn)
            for i, trig in enumerate([TRIGGER_MANUAL, TRIGGER_SCHEDULER, TRIGGER_API]):
                repo.record(
                    started_at=base + timedelta(minutes=i),
                    trigger=trig,
                    status="success",
                )

        runs = client.get("/api/v1/archive/runs").json()["data"]["runs"]
        assert [r["trigger"] for r in runs] == [TRIGGER_API, TRIGGER_SCHEDULER, TRIGGER_MANUAL]

    def test_limit_is_respected(self, client):
        base = datetime.now(UTC)
        with get_connection() as conn:
            repo = ArchiveRunRepository(conn)
            for i in range(5):
                repo.record(
                    started_at=base + timedelta(minutes=i),
                    trigger=TRIGGER_MANUAL,
                    status="success",
                )

        assert len(client.get("/api/v1/archive/runs?limit=2").json()["data"]["runs"]) == 2

    def test_limit_out_of_range_rejected(self, client):
        assert client.get("/api/v1/archive/runs?limit=0").status_code == 422
        assert client.get("/api/v1/archive/runs?limit=999").status_code == 422

    def test_policies_report_real_pending_counts(self, client):
        """待清理行数必须是真数 —— 这是页面上唯一能说明"下次会动多少"的数字。"""
        _insert_raw(datetime.now(UTC) - timedelta(days=100), processed=1)
        _insert_raw(datetime.now(UTC) - timedelta(days=100), processed=0)
        _insert_raw(datetime.now(UTC) - timedelta(days=1), processed=0)

        data = client.get("/api/v1/archive/runs").json()["data"]
        by_key = {p["key"]: p for p in data["policies"]}

        assert by_key["raw_processed"]["total"] == 1
        assert by_key["raw_processed"]["pending"] == 1
        assert by_key["raw_unprocessed"]["total"] == 2
        assert by_key["raw_unprocessed"]["pending"] == 1, "只有 100 天前那条过 90 天线"
        assert data["summary"]["pending_total"] == 2

    def test_policies_cover_every_retention_bucket(self, client):
        """六档策略都要露出来，包括此前零实现的归档表清理。"""
        keys = {p["key"] for p in client.get("/api/v1/archive/runs").json()["data"]["policies"]}
        assert keys == {
            "raw_processed",
            "raw_unprocessed",
            "signals",
            "logs",
            "raw_archive",
            "signals_archive",
        }

    def test_policies_expose_retention_days_from_settings(self, client, monkeypatch):
        monkeypatch.setattr(settings, "unprocessed_raw_retention_days", 123)
        policies = client.get("/api/v1/archive/runs").json()["data"]["policies"]
        row = next(p for p in policies if p["key"] == "raw_unprocessed")
        assert row["retention_days"] == 123

    def test_schedule_block_reflects_settings(self, client, monkeypatch):
        monkeypatch.setattr(settings, "archive_cron", "0 4 * * *")
        monkeypatch.setattr(settings, "archive_scheduler_enabled", False)
        schedule = client.get("/api/v1/archive/runs").json()["data"]["schedule"]
        assert schedule["cron"] == "0 4 * * *"
        assert schedule["enabled"] is False

    def test_endpoint_is_read_only(self, client):
        """只读端点：不得因为查看历史就触发一次清理。"""
        _insert_raw(datetime.now(UTC) - timedelta(days=100), processed=1)
        client.get("/api/v1/archive/runs")
        with get_connection() as conn:
            left = conn.execute("SELECT COUNT(*) FROM raw_projects").fetchone()[0]
            runs = conn.execute("SELECT COUNT(*) FROM archive_runs").fetchone()[0]
        assert left == 1, "查看历史不应搬走任何数据"
        assert runs == 0, "查看历史不应产生运行记录"


class TestArchiveRequiresAdmin:
    """归档历史含各表真实行数与运维配置，与 /settings 同一口径：仅管理员。"""

    ADMIN_KEY = "admin-key-for-archive-tests-0123456789"

    @pytest.fixture
    def auth_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "archive_auth.db"))
        monkeypatch.setattr(settings, "api_key", self.ADMIN_KEY)
        monkeypatch.setattr(settings, "auth_token_secret", "secret-for-archive-admin-tests")
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        return TestClient(create_app())

    def test_archive_in_admin_only_prefixes(self):
        from app.auth import ADMIN_ONLY_PREFIXES

        assert "/api/v1/archive" in ADMIN_ONLY_PREFIXES

    def test_no_credentials_rejected(self, auth_client):
        assert auth_client.get("/api/v1/archive/runs").status_code == 401

    def test_anonymous_token_forbidden(self, auth_client):
        token = auth_client.post("/api/v1/auth/anonymous").json()["access_token"]
        res = auth_client.get(
            "/api/v1/archive/runs",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res.status_code == 403

    def test_admin_key_allowed(self, auth_client):
        res = auth_client.get(
            "/api/v1/archive/runs",
            headers={"X-API-Key": self.ADMIN_KEY},
        )
        assert res.status_code == 200


class TestArchiveRunRepository:
    """仓储层的边界行为。"""

    @pytest.fixture(autouse=True)
    def _db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "archive_repo.db"))
        create_app()  # 触发 init_db

    def test_unknown_trigger_rejected(self):
        """拼错的 trigger 立刻报错，不在历史里留语义不明的值。"""
        with (
            get_connection() as conn,
            pytest.raises(ValueError, match="Unknown trigger"),
        ):
            ArchiveRunRepository(conn).record(
                started_at=datetime.now(UTC),
                trigger="cron-ish",
                status="success",
            )

    def test_limit_is_bounded(self):
        with get_connection() as conn:
            repo = ArchiveRunRepository(conn)
            for i in range(3):
                repo.record(
                    started_at=datetime.now(UTC) + timedelta(seconds=i),
                    trigger=TRIGGER_MANUAL,
                    status="success",
                )
            # 0 与负数不得被 SQLite 当成"不限制"
            assert len(repo.list_recent(limit=0)) == 1
            assert len(repo.list_recent(limit=-5)) == 1
            assert len(repo.list_recent(limit=10_000)) == 3

    def test_latest_returns_none_when_empty(self):
        with get_connection() as conn:
            assert ArchiveRunRepository(conn).latest() is None

    def test_counts_on_empty_table(self):
        with get_connection() as conn:
            assert ArchiveRunRepository(conn).counts() == {"total": 0, "failed": 0}
