"""决策推送（F1，ACTION_LOOP_DESIGN §2）测试：评估器 / 发送器 / 服务层 / API。

四个被测对象分层断言：

- 评估器是纯查询+纯判断 → 用内存库种子数据精确断言产出的事件集合；
- 发送器 → respx mock 网络（200 / 204 / 4xx / 5xx）；
- 服务层 → monkeypatch 发送器，断言重试与落库状态机；
- API → TestClient + 管理员锁正反断言。

「推送链路绝不能影响评分主链路」是本模块的第一设计约束，
evaluate_after_run 的吞错行为有专门测试钉住。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
import respx
from fastapi.testclient import TestClient

from app.config import settings
from app.db import init_db
from app.main import create_app
from app.notify.evaluator import NotifyEvent, detect_crossing, evaluate_events
from app.notify.service import dispatch_pending, insert_event, run_daily_digest
from app.utils.domain_allowlist import DomainNotAllowedError
from app.utils.fetcher import clear_cache, post

NOW = datetime.now(UTC)
NOW_STR = NOW.strftime("%Y-%m-%d %H:%M:%S")


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def client(tmp_path):
    """TestClient with an isolated database (same pattern as test_webhook)."""
    db_path = tmp_path / "test.db"
    prev_db_path = settings.db_path
    settings.db_path = str(db_path)
    init_db()
    app = create_app(db_override=lambda: None)
    yield TestClient(app)
    settings.db_path = prev_db_path


@pytest.fixture
def mem_conn():
    import sqlite3

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    try:
        yield conn
    finally:
        conn.close()


def _seed_project(
    conn,
    pid: str,
    *,
    name: str = "Test Project",
    score: int | None = 70,
    label: str | None = "FARM",
    created_at: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO projects (id, name, score, label, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (pid, name, score, label, created_at or NOW_STR, NOW_STR),
    )


def _seed_history(conn, pid: str, score: int, created_at: str) -> None:
    conn.execute(
        """
        INSERT INTO project_history (project_id, run_id, score, label, snapshot, created_at)
        VALUES (?, 'run-1', ?, 'FARM', '{}', ?)
        """,
        (pid, score, created_at),
    )


def _seed_watchlist_raw(conn, pid: str, raw_id: str, *, raw_data: dict | str | None = None) -> None:
    conn.execute("INSERT OR IGNORE INTO watchlist (project_id, user_id) VALUES (?, 'default')", (pid,))
    payload = raw_data if isinstance(raw_data, str) else json.dumps(raw_data or {"name": "Test Project"})
    conn.execute(
        """
        INSERT INTO raw_projects (
            raw_id, source_id, dedup_key, raw_data, discovered_at, processed, discovery_score, project_id
        ) VALUES (?, 'github', ?, ?, ?, 0, 0.5, ?)
        """,
        (raw_id, f"dedup-{raw_id}", payload, NOW_STR, pid),
    )
    conn.commit()


# ═══════════════════════════════════════════════════════════════
# Evaluator — detect_crossing (pure)
# ═══════════════════════════════════════════════════════════════


class TestDetectCrossing:
    def test_up_to_farm(self):
        assert detect_crossing(previous_score=60, current_score=65) == "up_farm"
        assert detect_crossing(previous_score=64, current_score=88) == "up_farm"

    def test_down_out_of_watch(self):
        assert detect_crossing(previous_score=55, current_score=49) == "down_watch"
        assert detect_crossing(previous_score=50, current_score=10) == "down_watch"

    def test_jitter_inside_bands_is_silent(self):
        """50-65 区间内的抖动、FARM 档内回落不破 50 —— 都不该吵用户。"""
        assert detect_crossing(previous_score=55, current_score=60) is None
        assert detect_crossing(previous_score=60, current_score=55) is None
        assert detect_crossing(previous_score=70, current_score=55) is None

    def test_missing_data_is_silent(self):
        assert detect_crossing(previous_score=None, current_score=70) is None
        assert detect_crossing(previous_score=70, current_score=None) is None


# ═══════════════════════════════════════════════════════════════
# Evaluator — evaluate_events (seeded in-memory DB)
# ═══════════════════════════════════════════════════════════════


class TestEvaluateEvents:
    def test_new_farm_and_digest(self, mem_conn):
        _seed_project(mem_conn, "p-1", name="Nova Farm", score=72, label="FARM")
        _seed_project(mem_conn, "p-2", name="Quiet Watch", score=55, label="WATCH")

        events = evaluate_events(mem_conn, now=NOW)
        by_type = {e.event_type for e in events}

        assert "new_farm" in by_type
        assert "daily_digest" in by_type
        farm = next(e for e in events if e.event_type == "new_farm")
        assert farm.event_key == "new_farm:p-1"
        digest = next(e for e in events if e.event_type == "daily_digest")
        assert "FARM 1" in digest.body

    def test_no_new_projects_means_no_digest(self, mem_conn):
        assert not [e for e in evaluate_events(mem_conn, now=NOW) if e.event_type == "daily_digest"]

    def test_score_crossing_both_directions(self, mem_conn):
        # 真实流程：save 每轮都写 history，「最新一条=当前分，次新一条=此前分」，
        # 所以每个项目要种两条历史才能构成一次跨线判定。
        _seed_project(mem_conn, "p-up", name="Riser", score=68, label="FARM")
        _seed_history(mem_conn, "p-up", 60, "2026-08-30 10:00:00")
        _seed_history(mem_conn, "p-up", 68, NOW_STR)
        _seed_project(mem_conn, "p-down", name="Faller", score=45, label="IGNORE")
        _seed_history(mem_conn, "p-down", 55, "2026-08-30 10:00:00")
        _seed_history(mem_conn, "p-down", 45, NOW_STR)
        # 抖动项目：55→60，不该出现
        _seed_project(mem_conn, "p-flat", name="Flat", score=60, label="WATCH")
        _seed_history(mem_conn, "p-flat", 55, "2026-08-30 10:00:00")
        _seed_history(mem_conn, "p-flat", 60, NOW_STR)

        crossings = [e for e in evaluate_events(mem_conn, now=NOW) if e.event_type == "score_crossing"]
        keys = {e.event_key for e in crossings}
        assert keys == {
            f"cross:p-up:up_farm:{NOW:%Y-%m-%d}",
            f"cross:p-down:down_watch:{NOW:%Y-%m-%d}",
        }

    def test_watchlist_signal_strong_flags_only(self, mem_conn):
        _seed_project(mem_conn, "p-w", name="Watched One", score=50, label="WATCH")
        _seed_watchlist_raw(mem_conn, "p-w", "r-fund", raw_data={"name": "Watched One", "recent_funding": True})
        _seed_watchlist_raw(
            mem_conn, "p-w", "r-plain", raw_data={"name": "Watched One"}
        )  # 无强信号 flag → 不该产出事件

        signals = [e for e in evaluate_events(mem_conn, now=NOW) if e.event_type == "watchlist_signal"]
        assert {e.event_key for e in signals} == {"signal:p-w:r-fund"}

    def test_corrupt_raw_data_row_is_skipped_not_fatal(self, mem_conn):
        """坏 raw_data 只损失这一条，绝不能让评估器炸掉（队列中毒的教训）。"""
        _seed_project(mem_conn, "p-w", name="Watched One", score=50, label="WATCH")
        _seed_watchlist_raw(mem_conn, "p-w", "r-corrupt", raw_data="{not json")

        signals = [e for e in evaluate_events(mem_conn, now=NOW) if e.event_type == "watchlist_signal"]
        assert signals == []

    def test_exclude_digest_for_pipeline_hook(self, mem_conn):
        _seed_project(mem_conn, "p-1", name="Nova Farm", score=72, label="FARM")
        events = evaluate_events(mem_conn, now=NOW, include_digest=False)
        assert all(e.event_type != "daily_digest" for e in events)
        # new_farm 不受门控：实时事件
        assert any(e.event_type == "new_farm" for e in events)


# ═══════════════════════════════════════════════════════════════
# Service — dedup / word list / dispatch state machine
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """隔离的 notify 库（跨 service 测试类共用）。"""
    prev = settings.db_path
    settings.db_path = str(tmp_path / "notify.db")
    init_db()
    yield settings.db_path
    settings.db_path = prev


class TestInsertEvent:
    def test_dedup_by_event_key_and_channel(self, mem_conn):
        event = NotifyEvent("new_farm", "new_farm:p-1", "t", "b")
        assert insert_event(mem_conn, event, "telegram") is True
        assert insert_event(mem_conn, event, "telegram") is False
        # 同事件不同通道是独立的一行
        assert insert_event(mem_conn, event, "discord_webhook") is True

    def test_unknown_event_type_rejected(self, mem_conn):
        with pytest.raises(ValueError, match="unknown notify event_type"):
            insert_event(mem_conn, NotifyEvent("bogus_type", "k", "t", "b"), "telegram")


class TestDispatchPending:
    def _seed_pending(self, event_key: str) -> None:
        from app.db import get_connection

        with get_connection() as conn:
            conn.commit()
            insert_event(conn, NotifyEvent("new_farm", event_key, "标题", "正文"), settings.notify_channel)
            conn.commit()

    async def test_send_updates_status(self, db_path, monkeypatch):
        self._seed_pending("k-ok")

        class FakeSender:
            channel = "telegram"

            async def send(self, title: str, body: str) -> None:
                return None

        monkeypatch.setattr("app.notify.service.get_sender", lambda: FakeSender())
        stats = await dispatch_pending()
        assert stats["sent"] == 1

        from app.db import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT status FROM notify_log").fetchone()
            assert row["status"] == "sent"

    async def test_three_failures_mark_failed(self, db_path, monkeypatch):
        self._seed_pending("k-bad")

        class FailingSender:
            channel = "telegram"

            async def send(self, title: str, body: str) -> None:
                raise RuntimeError("boom")

        monkeypatch.setattr("app.notify.service.get_sender", lambda: FailingSender())
        for _ in range(3):
            stats = await dispatch_pending()
            assert stats["failed"] == 1

        from app.db import get_connection

        with get_connection() as conn:
            row = conn.execute("SELECT status, attempts, last_error FROM notify_log").fetchone()
            assert row["status"] == "failed"
            assert row["attempts"] == 3
            assert "boom" in (row["last_error"] or "")


class TestRunDailyDigest:
    async def test_disabled_evaluates_but_never_sends(self, db_path, monkeypatch):
        """关开关 ≠ 停审计：评估照跑（留痕），但绝不构造发送器。"""
        monkeypatch.setattr(settings, "notify_enabled", False)

        def _boom():
            raise AssertionError("notify_enabled=False 时不得构造发送器")

        monkeypatch.setattr("app.notify.service.get_sender", _boom)
        stats = await run_daily_digest()
        assert stats["sent"] == 0


# ═══════════════════════════════════════════════════════════════
# Senders + fetcher.post (respx mock network)
# ═══════════════════════════════════════════════════════════════


class TestFetchPost:
    async def test_success_returns_status(self):
        clear_cache()
        with respx.mock:
            respx.post("https://api.telegram.org/botTOK/sendMessage").respond(200, json={"ok": True})
            status = await post(
                "https://api.telegram.org/botTOK/sendMessage",
                json_body={"chat_id": "1", "text": "hi"},
                max_retries=1,
            )
            assert status == 200

    async def test_204_no_content_is_success(self):
        """Discord webhook 成功返回 204 空体 —— post 不解析响应体正是为此。"""
        clear_cache()
        with respx.mock:
            route = respx.post("https://discord.com/api/webhooks/x/y").respond(204)
            status = await post("https://discord.com/api/webhooks/x/y", json_body={"content": "hi"}, max_retries=1)
            assert status == 204
            assert route.called

    async def test_client_error_not_retried(self):
        clear_cache()
        with respx.mock:
            route = respx.post("https://api.telegram.org/bot t/sendMessage").respond(401, json={"ok": False})
            with pytest.raises(RuntimeError, match="not retried"):
                await post("https://api.telegram.org/bot t/sendMessage", json_body={}, max_retries=3)
            # 401 只打了一次 —— 确定性失败不重试
            assert route.call_count == 1

    async def test_server_error_retries_then_raises(self):
        clear_cache()
        with respx.mock:
            respx.post("https://api.telegram.org/bot t/sendMessage").respond(500)
            with pytest.raises(RuntimeError, match="500"):
                await post("https://api.telegram.org/bot t/sendMessage", json_body={}, max_retries=2, retry_delay=0)

    async def test_unknown_domain_fail_closed(self):
        clear_cache()
        with pytest.raises(DomainNotAllowedError):
            await post("https://evil.example.com/hook", json_body={})


class TestSenders:
    async def test_telegram_sender(self):
        clear_cache()
        from app.notify.senders import TelegramSender

        with respx.mock:
            route = respx.post("https://api.telegram.org/botTOKEN/sendMessage").respond(200, json={"ok": True})
            await TelegramSender("TOKEN", "chat-1").send("标题", "正文")
            assert route.called
            payload = json.loads(route.calls.last.request.content)
            assert payload["chat_id"] == "chat-1"
            assert "标题" in payload["text"]

    async def test_discord_sender_204(self):
        clear_cache()
        from app.notify.senders import DiscordWebhookSender

        with respx.mock:
            respx.post("https://discord.com/api/webhooks/x/y").respond(204)
            await DiscordWebhookSender("https://discord.com/api/webhooks/x/y").send("标题", "正文")

    def test_get_sender_requires_credentials(self, monkeypatch):
        from app.notify import senders

        monkeypatch.setattr(settings, "notify_channel", "telegram")
        monkeypatch.setattr(settings, "telegram_bot_token", "")
        with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
            senders.get_sender()

        monkeypatch.setattr(settings, "notify_channel", "unknown_channel")
        with pytest.raises(RuntimeError, match="未知的通知通道"):
            senders.get_sender()


# ═══════════════════════════════════════════════════════════════
# API (admin-only)
# ═══════════════════════════════════════════════════════════════


ADMIN_HEADERS = {"X-API-Key": "test-admin-key-1234567890abcdef"}


class TestNotifyApi:
    @pytest.fixture
    def authed(self, client):
        """给测试环境配上 admin key（默认 open 模式下鉴权中间件不拦）。"""
        prev = settings.api_key
        settings.api_key = ADMIN_HEADERS["X-API-Key"]
        yield client
        settings.api_key = prev

    def test_test_endpoint_unconfigured_503(self, authed):
        r = authed.post("/api/v1/notify/test", headers=ADMIN_HEADERS)
        assert r.status_code == 503
        assert r.json()["error"]["code"] == "NOTIFY_NOT_CONFIGURED"

    def test_test_endpoint_configured_sends(self, authed, monkeypatch):
        monkeypatch.setattr(settings, "notify_channel", "telegram")
        monkeypatch.setattr(settings, "telegram_bot_token", "tok")
        monkeypatch.setattr(settings, "telegram_chat_id", "chat")

        class FakeSender:
            channel = "telegram"

            async def send(self, title: str, body: str) -> None:
                return None

        monkeypatch.setattr("app.routers.v1.notify.get_sender", lambda: FakeSender())
        r = authed.post("/api/v1/notify/test", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        assert r.json()["data"]["sent"] is True

    def test_status_endpoint_no_secrets(self, authed, monkeypatch):
        """status 只回显布尔与 cron，凭证值绝不出现 —— 克制口径。"""
        monkeypatch.setattr(settings, "telegram_bot_token", "super-secret-token")
        monkeypatch.setattr(settings, "telegram_chat_id", "chat-1")
        r = authed.get("/api/v1/notify/status", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        text = r.text
        assert "super-secret-token" not in text
        assert r.json()["data"]["telegram_configured"] is True

    def test_log_endpoint_lists_rows(self, authed):
        from app.db import get_connection
        from app.notify.service import insert_event

        with get_connection() as conn:
            insert_event(conn, NotifyEvent("new_farm", "new_farm:p-1", "标题", "正文"), "telegram")
            conn.commit()

        r = authed.get("/api/v1/notify/log", headers=ADMIN_HEADERS)
        assert r.status_code == 200
        items = r.json()["data"]["items"]
        assert any(i["event_key"] == "new_farm:p-1" for i in items)

    def test_anonymous_token_blocked(self, client):
        """整前缀管理员锁：匿名 token 一律 403（鉴权开启时）。"""
        prev = settings.api_key
        settings.api_key = "test-admin-key-1234567890abcdef"
        try:
            r = client.get("/api/v1/notify/status")
            assert r.status_code == 401  # 无任何凭证
        finally:
            settings.api_key = prev
