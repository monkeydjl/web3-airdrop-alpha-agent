"""Quarantine management endpoints."""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.quarantine import list_quarantined, quarantine_count, quarantine_raw, release_quarantine

router = APIRouter(tags=["quarantine"])


class QuarantineRequest(BaseModel):
    raw_id: str = Field(..., description="raw_projects.raw_id")
    reason: str = Field(..., min_length=1, max_length=500)


class ReleaseRequest(BaseModel):
    raw_id: str


@router.get("/quarantine")
def get_quarantine(limit: int = Query(100, ge=1, le=500)) -> dict[str, Any]:
    items = list_quarantined(limit=limit)
    for it in items:
        with suppress(json.JSONDecodeError):
            it["raw_data"] = json.loads(it["raw_data"]) if it.get("raw_data") else {}
    return {
        "ok": True,
        "data": {
            "count": quarantine_count(),
            "items": items,
        },
    }


@router.post("/quarantine")
def post_quarantine(req: QuarantineRequest) -> dict[str, Any]:
    ok = quarantine_raw(req.raw_id, req.reason)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "raw_id not found"})
    return {"ok": True, "data": {"raw_id": req.raw_id, "quarantined": True}}


@router.post("/quarantine/release")
def post_release(req: ReleaseRequest) -> dict[str, Any]:
    ok = release_quarantine(req.raw_id)
    if not ok:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": "raw_id not found"})
    return {"ok": True, "data": {"raw_id": req.raw_id, "released": True}}
