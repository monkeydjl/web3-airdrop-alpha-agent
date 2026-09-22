"""Daily Briefing API Router (每日 Alpha 晚报与行动清单路由).

GET /api/v1/daily-briefing/today
"""

from typing import Any
from fastapi import APIRouter
import structlog

from app.services.daily_briefing import generate_daily_briefing

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/daily-briefing", tags=["daily-briefing"])


@router.get("/today", summary="获取今日链上 Alpha 晚报与次日行动清单")
def get_today_briefing() -> dict[str, Any]:
    """聚合 24h 优质项目、Gas 黄金窗口、代币解锁与巨鲸异动，生成格式优雅的每日战报."""
    return generate_daily_briefing()
