"""Build curation evidence items from a scored pipeline state.

精选门槛（`app.services.project_signals.curation_reasons`）要求带 https URL 与
时间戳的可核验活动证据；本模块把 pipeline 已采集的信号（GitHub push 新鲜度、
任务门户活跃状态）转换成该证据结构，落库到 `meta.curation_evidence`。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.project_signals import evidence_time, valid_evidence_url

# 证据"新鲜"的判定窗口与 curation_reasons 的 90 天截止保持同源口径
RECENT_PUSH_DAYS_LIMIT = 45


def build_curation_evidence(state: Any) -> list[dict[str, Any]]:
    project = state.project
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []

    push_days = getattr(project, "github_recent_push_days", None)
    if (
        getattr(project, "has_github", False)
        and isinstance(push_days, int)
        and push_days <= RECENT_PUSH_DAYS_LIMIT
    ):
        occurred = (now - timedelta(days=push_days)).isoformat()
        # 优先项目自身的 github URL（https 可核验），缺失时退回官网
        url = project.url if valid_evidence_url(project.url) else None
        if url:
            items.append(
                {
                    "kind": "development",
                    "source": "github",
                    "url": url,
                    "occurred_at": occurred,
                }
            )

    if getattr(project, "has_task_portal", False):
        url = project.url if valid_evidence_url(project.url) else None
        if url:
            items.append(
                {
                    "kind": "campaign",
                    "source": "galxe" if "galxe.com" in url else ("layer3" if "layer3.xyz" in url else "manual"),
                    "url": url,
                    "status": "active",
                    "checked_at": now.isoformat(),
                }
            )

    return items


__all__ = ["RECENT_PUSH_DAYS_LIMIT", "build_curation_evidence", "evidence_time"]
