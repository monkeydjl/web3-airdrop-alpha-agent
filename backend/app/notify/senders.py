"""决策推送发送器（ACTION_LOOP_DESIGN.md §2.4）。

一条通道一个类。出站统一走 `utils/fetcher.post` —— 域名白名单、熔断器、
信号量对这条出口自动生效，senders 里不允许出现裸 httpx。

内容边界（设计文档 §2.4）：正文只含 name / score / label / url 级别的
摘要信息，不携带 raw_data 全文与采集原文 —— 外发面最小化。
"""

from __future__ import annotations

from typing import Protocol

import structlog

from app.config import settings
from app.utils import fetcher

logger = structlog.get_logger(__name__)

# Telegram Bot API 单条上限 4096；Discord webhook 单条上限 2000。
_TELEGRAM_MAX_CHARS = 4000
_DISCORD_MAX_CHARS = 2000


class Sender(Protocol):
    """一条推送通道的最低契约。channel 值与 notify_log.channel 对齐。"""

    channel: str

    async def send(self, title: str, body: str) -> None:
        """发送一条消息；失败抛异常（service 层负责重试与落库）。"""
        ...


class TelegramSender:
    """Telegram Bot API（api.telegram.org，白名单已登记）。"""

    channel = "telegram"

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    async def send(self, title: str, body: str) -> None:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        text = f"{title}\n\n{body}"[:_TELEGRAM_MAX_CHARS]
        await fetcher.post(
            url,
            json_body={
                "chat_id": self._chat_id,
                "text": text,
                "disable_web_page_preview": True,
            },
        )
        logger.info("notify.sent", channel=self.channel)


class DiscordWebhookSender:
    """Discord 频道 Webhook（discord.com，采集器 bot API 已在白名单）。"""

    channel = "discord_webhook"

    def __init__(self, webhook_url: str) -> None:
        self._webhook_url = webhook_url

    async def send(self, title: str, body: str) -> None:
        content = f"**{title}**\n{body}"[:_DISCORD_MAX_CHARS]
        # 204 No Content —— fetcher.post 不解析响应体，这正是它存在的理由
        await fetcher.post(self._webhook_url, json_body={"content": content})
        logger.info("notify.sent", channel=self.channel)


def get_sender() -> Sender:
    """按配置构造发送器；凭证缺失时给出「缺哪个键」的明确报错。"""
    channel = settings.notify_channel
    if channel == "telegram":
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            raise RuntimeError("notify channel 'telegram' 需要 TELEGRAM_BOT_TOKEN 与 TELEGRAM_CHAT_ID（.env）")
        return TelegramSender(settings.telegram_bot_token, settings.telegram_chat_id)
    if channel == "discord_webhook":
        if not settings.discord_notify_webhook_url:
            raise RuntimeError("notify channel 'discord_webhook' 需要 DISCORD_NOTIFY_WEBHOOK_URL（.env）")
        return DiscordWebhookSender(settings.discord_notify_webhook_url)
    raise RuntimeError(f"未知的通知通道：{channel}（可选 telegram / discord_webhook）")
