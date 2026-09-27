"""Token Unlocks API Router (代币解锁与抛压雷达路由).

GET /api/v1/unlocks/schedule
GET /api/v1/unlocks/project/{project_id}
"""

from typing import Any

import structlog
from fastapi import APIRouter, HTTPException, Path, Query

from app.services.token_unlock_radar import (
    get_project_unlock_details,
    get_upcoming_unlocks,
)
from app.utils.data_quality import mark_simulated, mark_simulated_list_response

# 解锁日程为静态演示数据，且日期为「now + N 天」滚动生成，永不真实
_UNLOCK_NOTE = "解锁日程为演示数据：日期由「当前日期 + 固定偏移」滚动生成，并非真实解锁时间线。"

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/unlocks", tags=["unlocks"])


@router.get("/schedule", summary="获取近期重点项目代币解锁与悬崖抛压时间线")
def get_unlock_schedule(
    limit: int = Query(20, ge=1, le=100, description="返回数量"),
    min_pressure: str | None = Query(None, description="最低抛压等级: critical, high, moderate, low"),
    sort_by: str = Query("date", description="排序方式: date (日期), value (释放估值), pct (流通占比)"),
) -> dict[str, Any]:
    """返回全生态即将到来的代币解锁日程、释放金额与抛压风险评级."""
    items = get_upcoming_unlocks(limit=limit, min_pressure=min_pressure, sort_by=sort_by)
    resp = mark_simulated_list_response(items, note=_UNLOCK_NOTE, count=len(items))
    return resp


@router.get("/project/{project_id}", summary="获取指定项目的专属代币解锁与抛压建议")
def get_single_project_unlock(
    project_id: str = Path(..., description="项目唯一标识 ID (如 celestia, arbitrum, monad)"),
) -> dict[str, Any]:
    """查询指定项目的专属代币解锁模型与应对策略."""
    detail = get_project_unlock_details(project_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"未找到项目 '{project_id}' 的代币解锁数据模型")
    return mark_simulated({"ok": True, "data": detail}, note=_UNLOCK_NOTE)
