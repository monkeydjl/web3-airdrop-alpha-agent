"""Pack / unpack extended project signals into projects.meta JSON.

Keeps scoring inputs (funding, docs, task portal, etc.) across rescore
without requiring a wide column migration.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.base import RawProject

# Fields stored under meta["signals"]
SIGNAL_KEYS = (
    "has_testnet",
    "has_points_program",
    "no_token_yet",
    "recent_funding",
    "has_docs",
    "has_whitepaper",
    "has_roadmap",
    "has_github",
    "has_twitter",
    "has_discord",
    "github_stars",
    "github_recent_push_days",
    "explicit_airdrop_mention",
    "tvl_usd",
    "description",
    "has_task_portal",
    "has_contract",
    "source_count",
    "roadmap_delivery",
    "sybil_friction",
    "funding_total_usd",
    "funding_rounds",
    "funding_last_date",
    "funding_investors",
    "funding_lead_investors",
    "funding_tier",
    "funding_quality",
)


def parse_meta(raw: Any) -> dict[str, Any]:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def signals_from_project(project: RawProject) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in SIGNAL_KEYS:
        if hasattr(project, key):
            val = getattr(project, key)
            if key in ("funding_investors", "funding_lead_investors"):
                out[key] = list(val or [])
            else:
                out[key] = val
    return out


def _is_missing(value: Any) -> bool:
    """判断一个信号值是否为"缺失"（而非"观测到的假/零"）。

    关键：Python 中 `False == 0` 且 `True == 1`，原实现用 `v == 0` 判空会把
    布尔 False 和数值 0 都当成缺失，形成单向棘轮——信号只能升不能降：
      - has_task_portal 从 True 变 False（活动已结束）永远写不回去
      - github_recent_push_days = 0（今天推送，最强新鲜度信号）被当作缺失丢弃，
        保留陈旧的 200，执行力子分因此从 75 掉到 47

    这里只把真正的"没有值"视为缺失：None / 空串 / 空列表 / unknown 占位。
    布尔 False 与数值 0 都是有效观测，必须写入。
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return False  # False 是观测结果，不是缺失
    if isinstance(value, (int, float)):
        return False  # 0 是观测结果（0 star / 今天推送 / 0 融资）
    if isinstance(value, str):
        return value.strip().lower() in ("", "unknown", "none")
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def merge_meta(existing: Any, project: RawProject) -> str:
    """Merge project signals into meta JSON string for DB storage."""
    meta = parse_meta(existing)
    prev = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}
    new_sig = signals_from_project(project)
    # 新值缺失且旧值有效时保留旧值；否则一律以新观测为准
    merged = dict(prev)
    for k, v in new_sig.items():
        if _is_missing(v) and k in prev and not _is_missing(prev[k]):
            continue
        merged[k] = v
    meta["signals"] = merged
    return json.dumps(meta, ensure_ascii=False)


def apply_signals_to_kwargs(meta: Any) -> dict[str, Any]:
    """Extract kwargs for RawProject construction from meta."""
    signals = parse_meta(meta).get("signals") or {}
    if not isinstance(signals, dict):
        return {}
    kwargs: dict[str, Any] = {}
    for key in SIGNAL_KEYS:
        if key not in signals:
            continue
        kwargs[key] = signals[key]
    # types
    if "github_stars" in kwargs:
        try:
            kwargs["github_stars"] = int(kwargs["github_stars"] or 0)
        except (TypeError, ValueError):
            kwargs["github_stars"] = 0
    if "funding_rounds" in kwargs:
        try:
            kwargs["funding_rounds"] = int(kwargs["funding_rounds"] or 0)
        except (TypeError, ValueError):
            kwargs["funding_rounds"] = 0
    if "funding_quality" in kwargs:
        try:
            kwargs["funding_quality"] = float(kwargs["funding_quality"] or 0)
        except (TypeError, ValueError):
            kwargs["funding_quality"] = 0.0
    if "source_count" in kwargs:
        try:
            kwargs["source_count"] = max(1, int(kwargs["source_count"] or 1))
        except (TypeError, ValueError):
            kwargs["source_count"] = 1
    for list_key in ("funding_investors", "funding_lead_investors"):
        if list_key in kwargs and not isinstance(kwargs[list_key], list):
            if isinstance(kwargs[list_key], str):
                kwargs[list_key] = [x.strip() for x in kwargs[list_key].split(",") if x.strip()]
            else:
                kwargs[list_key] = []
    return kwargs


def funding_public_view(meta: Any) -> dict[str, Any]:
    """API-facing funding block from meta.signals."""
    s = parse_meta(meta).get("signals") or {}
    if not isinstance(s, dict):
        s = {}
    return {
        "funding_total_usd": s.get("funding_total_usd"),
        "funding_rounds": s.get("funding_rounds") or 0,
        "funding_last_date": s.get("funding_last_date"),
        "funding_investors": s.get("funding_investors") or [],
        "funding_lead_investors": s.get("funding_lead_investors") or [],
        "funding_tier": s.get("funding_tier") or "unknown",
        "funding_quality": s.get("funding_quality") or 0,
        "recent_funding": bool(s.get("recent_funding")),
    }
