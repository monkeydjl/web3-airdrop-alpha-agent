"""Smart Money Radar Router (聪明钱监控目标与社交热度路由).

GET /api/v1/smart-money/feed

诚实口径：此端点历史上返回编造的巨鲸动态与假社交增速，已清理——
动态如实为空、榜单排序基于真实项目评分。巨鲸监控需要真实链上数据源，
接入前该端点整体打 ``simulated`` 标记（榜单本身是真实评分，但「聪明钱雷达」
的产品语义尚未兑现，宁可低报不可高报）。
"""

from typing import Any

import structlog
from fastapi import APIRouter

from app.services.smart_money_radar import get_smart_money_and_social_feed
from app.utils.data_quality import mark_simulated

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/smart-money", tags=["smart_money"])


@router.get("/feed", summary="获取聪明钱监控目标清单与项目热度榜（真实评分排序）")
def get_feed() -> dict[str, Any]:
    """返回监控白名单与真实评分热度榜；巨鲸动态在接入链上数据源前如实为空."""
    feed = get_smart_money_and_social_feed()
    return mark_simulated(
        feed,
        note="巨鲸动态暂无真实链上数据源（如实为空）；热度榜排序基于真实项目评分，非社交增速。",
    )
