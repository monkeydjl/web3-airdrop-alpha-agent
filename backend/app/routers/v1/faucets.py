"""Testnet faucets tracking and cooldown API router."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Path, Query, Request

from app.auth import get_current_user
from app.services.user_scope import DEFAULT_USER
from app.services.faucet_registry import (
    FREE_FAUCETS,
    list_faucets_with_status,
    probe_faucets_liveness,
    record_faucet_claim,
    reset_faucet_claim,
)

router = APIRouter(tags=["faucets"])


@router.get(
    "/faucets/probe",
    summary="实时测速探测所有测试网水龙头存活性",
    description="免 Key 毫秒级探测主流测试网水龙头当前在线状态与网络响应延迟。",
)
def probe_faucets(
    force_refresh: bool = Query(False, description="是否强制刷新探测"),
) -> dict[str, Any]:
    items = probe_faucets_liveness(force_refresh=force_refresh)
    return {
        "ok": True,
        "data": {
            "probes": items,
            "total": len(items),
            "online_count": sum(1 for p in items if p["status"] == "online"),
        },
    }


@router.get(
    "/faucets",
    summary="获取测试网水龙头列表与冷却状态",
    description="返回系统精选的免费测试网水龙头列表，含实时 24h 冷却倒计时与领取指引。",
)
def get_faucets(
    req: Request,
    chain: str | None = Query(None, description="按链代号筛选 (如 sepolia, berachain_bartio)"),
) -> dict[str, Any]:
    user = get_current_user(req)
    uid = user.get("user_id") or DEFAULT_USER
    if uid == "anonymous":
        uid = DEFAULT_USER

    items = list_faucets_with_status(user_id=uid)
    if chain:
        chain_lower = chain.strip().lower()
        items = [f for f in items if f.get("chain", "").lower() == chain_lower]

    ready_count = sum(1 for f in items if f.get("status") == "ready")
    cooling_count = sum(1 for f in items if f.get("status") == "cooling")

    return {
        "ok": True,
        "data": {
            "faucets": items,
            "total": len(items),
            "ready_count": ready_count,
            "cooling_count": cooling_count,
        },
    }


@router.post(
    "/faucets/{faucet_id}/claim",
    summary="打卡标记水龙头已领取",
    description="标记当前用户已从指定水龙头领水，自动开启 24 小时冷却倒计时。",
)
def claim_faucet(
    req: Request,
    faucet_id: str = Path(..., description="水龙头 ID (如 sepolia-pow)"),
) -> dict[str, Any]:
    faucet = next((f for f in FREE_FAUCETS if f["id"] == faucet_id), None)
    if not faucet:
        raise HTTPException(
            status_code=404,
            detail={"code": "FAUCET_NOT_FOUND", "message": f"Faucet '{faucet_id}' not found"},
        )

    user = get_current_user(req)
    uid = user.get("user_id") or DEFAULT_USER
    if uid == "anonymous":
        uid = DEFAULT_USER

    updated = record_faucet_claim(user_id=uid, faucet_id=faucet_id)
    return {
        "ok": True,
        "data": updated,
    }


@router.delete(
    "/faucets/{faucet_id}/claim",
    summary="重置水龙头冷却状态",
    description="清除水龙头领取记录，将状态重置为「可领取」。",
)
def reset_faucet(
    req: Request,
    faucet_id: str = Path(..., description="水龙头 ID (如 sepolia-pow)"),
) -> dict[str, Any]:
    faucet = next((f for f in FREE_FAUCETS if f["id"] == faucet_id), None)
    if not faucet:
        raise HTTPException(
            status_code=404,
            detail={"code": "FAUCET_NOT_FOUND", "message": f"Faucet '{faucet_id}' not found"},
        )

    user = get_current_user(req)
    uid = user.get("user_id") or DEFAULT_USER
    if uid == "anonymous":
        uid = DEFAULT_USER

    reset_faucet_claim(user_id=uid, faucet_id=faucet_id)
    return {
        "ok": True,
        "message": f"Faucet {faucet_id} cooldown reset to ready",
    }


@router.get(
    "/faucets/health",
    summary="探测测试网水龙头实时存量与健康状态",
    description="通过免 Key 公共 RPC 与探活检测水龙头金库资金充足度与网络可用性。",
)
async def get_faucets_health(
    faucet_id: str | None = Query(None, description="按指定水龙头 ID 探测"),
) -> dict[str, Any]:
    from app.services.faucet_registry import check_faucets_liveness

    res = await check_faucets_liveness(faucet_id=faucet_id)
    return {
        "ok": True,
        "data": {
            "statuses": res,
            "total_checked": len(res),
            "healthy_count": sum(1 for f in res if f["health"] == "healthy"),
            "low_balance_count": sum(1 for f in res if f["health"] == "low_balance"),
            "depleted_count": sum(1 for f in res if f["health"] == "depleted"),
        },
    }

