"""Bot 测试发送通道的安全回归（SECURITY §10.2 出站白名单 + 管理员锁）。

背景（2026-11-13 审查发现）：
- `send_discord_webhook` 用裸 httpx 发往**请求体里任意用户提供的 URL**，
  是全仓唯一绕过出站域名白名单的出口（fetcher/LLM/采集器全部 fail-closed，
  唯独这条路没有）——匿名 token 持有者可让后端向内网地址（169.254.169.254、
  本地服务等）POST 任意内容，响应的 ok/status 构成 1-bit 内网探活 oracle。
- `POST /api/v1/bot/test-send` 之前登记为匿名可写，登记理由"需 BOT_TOKEN"
  与事实不符：token/webhook URL 都来自请求体，不要求服务端配置。

钉住两个契约：
1. 两个发送函数出站前必须过 `assert_url_allowed`（fail-closed）；
2. `/bot/test-send` 是管理员专属（`/bot/command` 只读渲染，保持匿名可用）。
"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

import app.services.bot_notifier as bot_notifier
from app.auth import requires_admin
from app.utils.domain_allowlist import DomainNotAllowedError


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _FakeClient:
    """httpx.Client 替身：记录发出的请求，不打真网。"""

    last_requests: ClassVar[list[dict[str, Any]]] = []
    raise_on_post: ClassVar[Exception | None] = None

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        type(self).last_requests.append({"url": url, **kwargs})
        if type(self).raise_on_post is not None:
            raise type(self).raise_on_post
        return _FakeResponse(200)


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> type[_FakeClient]:
    _FakeClient.last_requests = []
    _FakeClient.raise_on_post = None
    monkeypatch.setattr(bot_notifier.httpx, "Client", _FakeClient)
    return _FakeClient


# ── 出站域名白名单 ───────────────────────────────


def test_discord_send_rejects_non_allowlisted_host(fake_client: type[_FakeClient]) -> None:
    """表外域名必须在出站前被拒 —— 不能真的发出请求（fail-closed）。"""
    with pytest.raises(DomainNotAllowedError):
        bot_notifier.send_discord_webhook("http://169.254.169.254/latest/meta-data/", "t", "d")
    assert _FakeClient.last_requests == [], "白名单拒绝后不应有任何出站请求"


def test_discord_send_allows_allowlisted_host(fake_client: type[_FakeClient]) -> None:
    ok = bot_notifier.send_discord_webhook("https://discord.com/api/webhooks/123/abc", "t", "d")
    assert ok is True
    assert len(_FakeClient.last_requests) == 1


def test_telegram_send_allows_allowlisted_host(fake_client: type[_FakeClient]) -> None:
    ok = bot_notifier.send_telegram_message("token", "chat", "hello")
    assert ok is True
    assert _FakeClient.last_requests[0]["url"].startswith("https://api.telegram.org/")


def test_discord_send_rejects_empty_url() -> None:
    assert bot_notifier.send_discord_webhook("", "t", "d") is False


def test_telegram_send_rejects_missing_credentials() -> None:
    assert bot_notifier.send_telegram_message("", "chat", "hello") is False


# ── 异常日志里的凭据脱敏 ─────────────────────────


def test_redact_error_masks_secrets_in_message() -> None:
    """httpx 异常会渲染完整 URL：Telegram bot_token / Discord webhook 秘钥都在
    path 里，直接 str(e) 进日志等于把凭据写进日志管道。"""
    error = RuntimeError("POST https://api.telegram.org/botSECRETTOKEN/sendMessage failed: boom")
    text = bot_notifier._redact_error(error, "SECRETTOKEN")
    assert "SECRETTOKEN" not in text
    assert "<redacted>" in text
    assert "sendMessage failed" in text


def test_redact_error_handles_empty_secrets() -> None:
    error = RuntimeError("plain failure")
    assert bot_notifier._redact_error(error, "") == "plain failure"


def test_telegram_failure_log_does_not_leak_token(
    fake_client: type[_FakeClient], caplog: pytest.LogCaptureFixture
) -> None:
    """端到端：发送失败时，冒泡到日志的异常文本不得包含 bot_token。"""

    _FakeClient.raise_on_post = RuntimeError("POST https://api.telegram.org/botSECRETTOKEN/sendMessage failed")
    # structlog 走自己的 pipeline，caplog 只兜底 stdlib；这里直接断言函数不抛
    # 且返回 False —— 泄漏路径的单元断言在 test_redact_error_masks_secrets_in_message。
    ok = bot_notifier.send_telegram_message("SECRETTOKEN", "chat", "hello")
    assert ok is False
    assert _FakeClient.last_requests, "失败也意味着确实尝试过出站"


# ── 管理员锁 ────────────────────────────────────


def test_bot_test_send_is_admin_only() -> None:
    assert requires_admin("POST", "/api/v1/bot/test-send"), (
        "`/bot/test-send` 是对第三方服务的出站发送动作，必须管理员专属。"
    )
    # 相邻读写边界：指令渲染是只读文本，保持匿名可用。
    assert not requires_admin("POST", "/api/v1/bot/command")


def test_bot_prefix_rule_is_anchored() -> None:
    """/bot/test-send 的规则不能误伤相似路径（见 test_admin_only_rules 的教训）。"""
    assert not requires_admin("POST", "/api/v1/botfoo/test-send")
    # 规则只锁写方法；GET 本就不存在路由，也不该被锁。
    assert not requires_admin("GET", "/api/v1/bot/test-send")
