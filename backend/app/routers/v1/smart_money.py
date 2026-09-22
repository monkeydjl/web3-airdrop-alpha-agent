"""Smart Money Radar Router (聪明钱潜伏与社交异动路由).

GET /api/v1/smart-money/feed
"""

from typing import Any
from fastapi import APIRouter
import structlog

from app.services.smart_money_radar import get_smart_money_and_social_feed

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/smart-money", tags=["smart_money"])


@router.get("/feed", summary="获取聪明钱巨鲸最新异动与社交讨论暴增榜")
def get_feed() -> dict[str, Any]:
    """返回知名巨鲸链上最新操作与社交热度环比飙升榜."""
    return get_smart_money_and_social_feed()
