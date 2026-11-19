"""notify 发送器凭据脱敏回归（2026-11-19 深审 P1）。

背景：Telegram bot token / Discord webhook key 内嵌在出站 URL 里。
`fetcher.post` 抛出的异常文本携带完整 URL，service 层把 `str(exc)` 原样
写进 notify_log.last_error 与 notify.send_failed 日志，且 /notify/log 接口
回显 last_error —— 凭证经数据库、日志、API 三处泄漏。

契约：senders 抛出的异常文本**必须已脱敏**（凭证以 <redacted> 代替），
service 层的入库/日志/回显天然安全。
"""

from __future__ import annotations

import contextlib

import pytest

from app.utils import fetcher


@pytest.fixture
def dispatch_env(monkeypatch: pytest.MonkeyPatch, tmp_path):
    """独立的 notify_log 库 + fetcher.post 替身 + connection_scope 注入。"""
    import sqlite3

    from app.db import DbConnection, init_db

    # dispatch 经 asyncio.to_thread 记录失败 —— 与生产 _connect_sqlite 同款跨线程语义
    raw = sqlite3.connect(":memory:", check_same_thread=False)
    raw.row_factory = sqlite3.Row
    conn = DbConnection(raw, kind="sqlite")
    init_db(conn)

    captured_errors: list[str] = []

    async def boom_post(url: str, **kwargs) -> int:
        captured_errors.append(url)
        raise RuntimeError(f"POST {url} failed: connect timeout")

    monkeypatch.setattr(fetcher, "post", boom_post)

    import app.notify.service as service_mod
    from app.db import connection_scope as _real_scope  # noqa: F401

    @contextlib.contextmanager
    def scope(*args: object, **kwargs: object):
        yield conn

    monkeypatch.setattr(service_mod, "connection_scope", scope)
    return {
        "conn": conn,
        "raw": raw,
        "captured_urls": captured_errors,
        "real_close": lambda: conn.close(),
    }


# ── senders 层脱敏 ──────────────────────────────


async def test_telegram_error_redacts_bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.notify.senders import TelegramSender

    sender = TelegramSender("SECRETTOKEN", "chat-1")

    async def boom(url: str, **kwargs) -> int:
        raise RuntimeError(f"POST {url} failed: connect timeout")

    monkeypatch.setattr(fetcher, "post", boom)

    with pytest.raises(RuntimeError) as exc_info:
        await sender.send("t", "b")

    assert "SECRETTOKEN" not in str(exc_info.value), f"bot token 随异常文本泄漏：{exc_info.value}"


async def test_discord_error_redacts_webhook_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.notify.senders import DiscordWebhookSender

    url = "https://discord.com/api/webhooks/12345/WEBHOOKKEY"
    sender = DiscordWebhookSender(url)

    async def boom(u: str, **kwargs) -> int:
        raise RuntimeError(f"POST {u} failed: connect timeout")

    monkeypatch.setattr(fetcher, "post", boom)

    with pytest.raises(RuntimeError) as exc_info:
        await sender.send("t", "b")

    assert "WEBHOOKKEY" not in str(exc_info.value), f"webhook key 随异常文本泄漏：{exc_info.value}"


# ── dispatch 级集成：notify_log.last_error 无凭证 ────────────────


async def test_notify_log_last_error_has_no_credentials(dispatch_env: dict, monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：发送失败后 notify_log.last_error 不得含 token（API 会回显它）。"""
    from datetime import UTC, datetime

    from app.config import settings
    from app.notify.service import dispatch_pending

    conn = dispatch_env["conn"]
    now = datetime.now(UTC)
    event_key = f"daily_digest:{now.date().isoformat()}"
    conn.execute(
        """
        INSERT INTO notify_log (event_type, event_key, channel, title, body,
                                status, attempts, created_at)
        VALUES ('daily_digest', ?, 'telegram', 't', 'b', 'pending', 0, ?)
        """,
        (event_key, now.isoformat()),
    )
    conn.commit()

    monkeypatch.setattr(settings, "notify_channel", "telegram")
    monkeypatch.setattr(settings, "telegram_bot_token", "SECRETTOKEN")
    monkeypatch.setattr(settings, "telegram_chat_id", "chat-1")

    result = await dispatch_pending()
    assert result["failed"] == 1

    row = conn.execute("SELECT last_error FROM notify_log WHERE event_key = ?", (event_key,)).fetchone()
    last_error = dict(row)["last_error"] or ""
    assert "SECRETTOKEN" not in last_error, f"notify_log.last_error 泄漏 bot token：{last_error!r}"
    assert last_error, "last_error 不应为空 —— 失败原因要保留（脱敏后）"
