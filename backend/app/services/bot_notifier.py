"""Interactive Alpha Bot & Real-time Notifier Service (Telegram / Discord 实时播报与交互式指令机器人).

支持向 Telegram 群/私聊与 Discord Webhook 推送高确定性 Alpha 信号，
并支持处理 /alpha, /gas, /faucets 等实时双向交互指令。
"""

import httpx
import structlog
from typing import Any

from app.db import dict_from_row, get_connection

logger = structlog.get_logger(__name__)


def handle_bot_command(command: str) -> dict[str, Any]:
    """处理 Bot 指令并返回格式化响应文本."""
    cmd = command.strip().lower()
    if cmd.startswith("/"):
        cmd = cmd[1:]

    parts = cmd.split()
    root_cmd = parts[0] if parts else "help"

    if root_cmd in ("start", "help"):
        help_text = (
            "🤖 *Web3 Airdrop Alpha Agent 交互助手已就绪*\n\n"
            "可用指令列表：\n"
            "• `/alpha` - 获取今日综合评分最高的 Top 5 FARM 重点项目\n"
            "• `/gas` - 查询当前全链 Gas 费率与最佳低磨损时段\n"
            "• `/faucets` - 查看当前高可用水龙头与存活状态\n"
            "• `/calendar` - 查询 48h 内紧急快照与 TGE 倒计时\n"
            "• `/help` - 显示本帮助菜单\n\n"
            "💡 _系统全天候运行四路 AI Agent 与链上多源验证，助你捕获第一手空投先机！_"
        )
        return {"ok": True, "command": root_cmd, "reply": help_text}

    elif root_cmd == "alpha":
        conn = get_connection()
        try:
            rows = conn.execute(
                """
                SELECT id, name, sector, score, label, stage
                FROM projects
                WHERE label = 'FARM' AND (source != 'historical_backfill' OR source IS NULL)
                ORDER BY score DESC LIMIT 5
                """
            ).fetchall()
            projects = [dict_from_row(r) for r in rows]
        finally:
            conn.close()

        if not projects:
            reply = "🔍 暂未检索到 FARM 级项目，系统持续扫描中。"
        else:
            lines = ["🎯 *今日精选 Top 5 重点空投项目 (FARM)*\n"]
            for i, p in enumerate(projects, 1):
                lines.append(
                    f"{i}. *{p['name']}* (`{p.get('sector') or 'Web3'}`)\n"
                    f"   ⭐ 综合评分: *{p['score']}* 分 | 阶段: `{p.get('stage') or '早期'}`\n"
                    f"   🔗 详情: https://airdrop.agent/projects/{p['id']}"
                )
            reply = "\n\n".join(lines)

        return {"ok": True, "command": root_cmd, "reply": reply}

    elif root_cmd == "gas":
        from app.services.gas_tracker import get_all_chains_gas_summary

        summary = get_all_chains_gas_summary()
        chains = summary["chains"]

        lines = ["⛽ *全链实时 Gas 极佳交互雷达*\n"]
        for c_key in ["ethereum", "arbitrum", "base", "optimism", "polygon", "bsc"]:
            if c_key in chains:
                c = chains[c_key]
                lines.append(f"• {c['icon']} *{c['name']}*: `{c['gwei']} Gwei` ({c['status_zh']})")

        rec = summary["recommendations"]["current_recommendation"]
        lines.append(f"\n💡 *操作建议*: {rec}")
        return {"ok": True, "command": root_cmd, "reply": "\n".join(lines)}

    elif root_cmd == "faucets":
        from app.services.faucet_registry import list_faucets

        faucets = list_faucets()
        alive = [f for f in faucets if f.get("status") in ("available", "healthy")]

        lines = [f"💧 *当前高可用测试网水龙头 (存活 {len(alive)}/{len(faucets)})*\n"]
        for f in alive[:6]:
            lines.append(
                f"• *{f.get('network_name')}* ({f.get('faucet_type', '公开')})\n"
                f"   单次领水: `{f.get('drip_amount')}` | [立即前往]({f.get('faucet_url')})"
            )
        return {"ok": True, "command": root_cmd, "reply": "\n\n".join(lines)}

    elif root_cmd == "calendar":
        from app.services.airdrop_calendar import get_calendar_events

        events = get_calendar_events()
        urgent = [e for e in events if e.get("urgency") in ("urgent", "soon")][:5]

        if not urgent:
            reply = "📅 近期暂无 7 天内紧急截止的空投事件。"
        else:
            lines = ["📅 *近期关键空投快照与 TGE 倒计时*\n"]
            for e in urgent:
                tag = "🚨" if e["urgency"] == "urgent" else "⏰"
                lines.append(
                    f"{tag} *{e['title']}*\n"
                    f"   项目: {e['project_name']} | 剩余: *{e['days_remaining']} 天* ({e['event_type_zh']})"
                )
            reply = "\n\n".join(lines)

        return {"ok": True, "command": root_cmd, "reply": reply}

    else:
        return {
            "ok": False,
            "command": root_cmd,
            "reply": f"未知指令 `/{root_cmd}`，发送 `/help` 查看支持的全部指令。",
        }


def send_discord_webhook(webhook_url: str, title: str, description: str, color: int = 0x10B981) -> bool:
    """向 Discord Webhook 发送结构化 Embeds 消息."""
    if not webhook_url or not webhook_url.startswith("http"):
        return False

    payload = {
        "embeds": [
            {
                "title": title,
                "description": description,
                "color": color,
                "footer": {"text": "Web3 Airdrop Alpha Agent"},
            }
        ]
    }

    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(webhook_url, json=payload)
            return resp.status_code in (200, 204)
    except Exception as e:
        logger.warning("bot_notifier.discord_failed", error=str(e))
        return False


def send_telegram_message(bot_token: str, chat_id: str, text: str) -> bool:
    """向 Telegram 发送消息."""
    if not bot_token or not chat_id:
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }

    try:
        with httpx.Client(timeout=4.0) as client:
            resp = client.post(url, json=payload)
            return resp.status_code == 200
    except Exception as e:
        logger.warning("bot_notifier.telegram_failed", error=str(e))
        return False
