"""Bot Router (Telegram / Discord 机器人路由).

POST /api/v1/bot/command - 模拟或执行 Bot 指令
POST /api/v1/bot/test-send - 测试向 Discord / Telegram 发送通知
"""

from typing import Any
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import structlog

from app.services.bot_notifier import (
    handle_bot_command,
    send_discord_webhook,
    send_telegram_message,
)

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/bot", tags=["bot"])


class CommandRequest(BaseModel):
    command: str = Field(..., description="输入的指令，如 /alpha, /gas, /faucets, /help")


class TestSendRequest(BaseModel):
    channel: str = Field(..., description="discord 或 telegram")
    webhook_url: str | None = Field(None, description="Discord Webhook URL")
    bot_token: str | None = Field(None, description="Telegram Bot Token")
    chat_id: str | None = Field(None, description="Telegram Chat ID")
    title: str = Field("🎯 [Web3 Alpha Agent] 测试警报已触发", description="消息标题")
    message: str = Field("系统与通知网关连接畅通，Agent 持续监听最新链上空投信号。", description="消息正文")


@router.post("/command", summary="执行交互式 Bot 指令并返回格式化文本")
def execute_command(req: CommandRequest) -> dict[str, Any]:
    """执行 Bot 指令（/alpha, /gas, /faucets, /calendar, /help）."""
    res = handle_bot_command(req.command)
    return res


@router.post("/test-send", summary="测试向 Discord / Telegram 发送实时消息")
def test_send_message(req: TestSendRequest) -> dict[str, Any]:
    """发送测试通知."""
    if req.channel.lower() == "discord":
        if not req.webhook_url:
            raise HTTPException(status_code=400, detail="webhook_url is required for Discord")
        ok = send_discord_webhook(req.webhook_url, req.title, req.message)
        return {"ok": ok, "channel": "discord", "status": "sent" if ok else "failed"}

    elif req.channel.lower() == "telegram":
        if not req.bot_token or not req.chat_id:
            raise HTTPException(status_code=400, detail="bot_token and chat_id are required for Telegram")
        full_text = f"*{req.title}*\n\n{req.message}"
        ok = send_telegram_message(req.bot_token, req.chat_id, full_text)
        return {"ok": ok, "channel": "telegram", "status": "sent" if ok else "failed"}

    else:
        raise HTTPException(status_code=400, detail=f"Unsupported channel: {req.channel}")
