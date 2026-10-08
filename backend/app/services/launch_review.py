"""已发币项目每日复查：确认已发币且没有后续空投路径的项目从默认列表隐藏。

背景（2026-10-08）：入库门只拦**新**原始行，库里早已入库的已发币项目不会因此消失；
一次手工清理又把 RootData「没写未发币」误当成「已发币」删掉了约 30 个项目。
这里换成可逆的做法：

- **只隐藏，不删除**：写 ``projects.hidden_reason`` / ``hidden_at``，默认列表、看板、
  日报等读面带 ``hidden_reason IS NULL`` 过滤；``include_hidden=true`` 仍能查到。
- **只认确认已发币**：判定与入库门同一口径（``token_launch_confirmed`` 三态，
  ADR-015 2026-10-08 补充）。来源给不出发币证据 = 状态未知，不隐藏。
- **自动恢复**：之后出现积分计划 / 任务入口 / 明确空投措辞，或证据不再支持
  「确认已发币」，下一轮复查即清掉隐藏标记。只清本模块写的原因，不碰别的。
- **用户在做的项目不隐藏**：有 active 参与计划的项目始终保留在列表里。

隐藏不改 ``updated_at``：这是展示层的开关，不是项目内容变化（同 vitals 的约束，
避免冲掉 AI 简报缓存的新鲜度判定）。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import structlog

from app.agents.collector import CollectorAgent
from app.db import connection_scope, dict_from_row
from app.services.project_signals import parse_meta, signals_of
from app.utils.normalize import merge_raw_records

logger = structlog.get_logger(__name__)

HIDDEN_REASON_ALREADY_LAUNCHED = "already_launched_no_path"

# 积分只认严格证据 explicit_points_program：宽松的 has_points_program 把 restaking /
# incentive 也算进去，首轮实测 20 个确认已发币项目全靠它躲过隐藏。
_PATH_FLAGS = ("explicit_points_program", "has_task_portal", "explicit_airdrop_mention")
_MERGE_KEYS = ("no_token_yet", "token_launch_confirmed", *_PATH_FLAGS)


def _latest_raw_flags_by_project(conn: Any) -> dict[str, list[dict[str, Any]]]:
    """每个项目、每个来源取最新一条原始行，推断成合并用的 flag 记录。

    隔离行也算：被入库门隔离的行同样是「这个源当下怎么说」的证据。
    """
    rows = conn.execute(
        """
        SELECT project_id, source_id, raw_data, discovered_at
        FROM raw_projects
        WHERE project_id IS NOT NULL
        ORDER BY discovered_at DESC
        """
    ).fetchall()
    seen: set[tuple[str, str]] = set()
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        r = dict_from_row(row)
        pid, source_id = str(r["project_id"]), str(r["source_id"])
        if (pid, source_id) in seen:
            continue
        seen.add((pid, source_id))
        try:
            raw_data = json.loads(r["raw_data"]) if r.get("raw_data") else {}
        except (ValueError, TypeError):
            continue  # 坏行由采集器隔离，这里不替它判定
        if not isinstance(raw_data, dict):
            continue
        flags = CollectorAgent._infer_airdrop_flags(source_id, raw_data)
        record = {k: flags.get(k) for k in _MERGE_KEYS}
        record["name"] = raw_data.get("name") or ""
        record["source"] = source_id
        out.setdefault(pid, []).append(record)
    return out


def assess_project(signals: dict[str, Any], raw_records: list[dict[str, Any]]) -> tuple[bool, bool]:
    """返回 (确认已发币, 有后续空投路径)。

    - 有原始行：按采集口径跨源合并（任一源有发币证据即确认，no_token_yet AND 合并）。
      库内信号若明确写着 ``no_token_yet=True``（人工修正或较新的评分结论），
      证据冲突，按未知处理——宁可多留一个，也不误藏。
    - 没有原始行（已归档 / 早期导入）：只看库内信号，缺 ``token_launch_confirmed``
      即未知。
    - 后续路径：原始行与库内信号任一处看到即算（富化器写进 meta 的证据也作数）。
      积分只看 ``explicit_points_program``；库内信号里的宽松 ``has_points_program``
      不作数 —— 它正是被通用词污染的那个字段。
    """
    has_path = any(bool(signals.get(k)) for k in _PATH_FLAGS)
    if raw_records:
        merged = merge_raw_records(raw_records, source_key="source")
        has_path = has_path or any(bool(merged.get(k)) for k in _PATH_FLAGS)
        confirmed = bool(merged.get("token_launch_confirmed")) and not merged.get("no_token_yet")
        if signals.get("no_token_yet") is True:
            confirmed = False
    else:
        confirmed = signals.get("token_launch_confirmed") is True and signals.get("no_token_yet") is not True
    return confirmed, has_path


def run_launch_review(conn: Any = None) -> dict[str, int]:
    """跑一轮复查，返回统计。``conn`` 注入时为借用连接，不在此关闭。"""
    stats = {"reviewed": 0, "hidden": 0, "unhidden": 0, "kept_hidden": 0, "protected_active_plan": 0}
    with connection_scope(conn) as db:
        _review(db, stats)
    logger.info("launch_review.completed", **stats)
    return stats


def _review(db: Any, stats: dict[str, int]) -> None:
    try:
        raw_by_project = _latest_raw_flags_by_project(db)
        active_plans = {
            str(dict_from_row(r)["project_id"])
            for r in db.execute(
                "SELECT DISTINCT project_id FROM participation_plans WHERE status = 'active'"
            ).fetchall()
        }
        rows = db.execute(
            """
            SELECT id, name, meta, hidden_reason
            FROM projects
            WHERE source != 'historical_backfill' OR source IS NULL
            """
        ).fetchall()

        now = datetime.now(UTC)
        to_hide: list[tuple[str, str]] = []
        to_unhide: list[tuple[str, str]] = []
        for row in rows:
            d = dict_from_row(row)
            pid = str(d["id"])
            stats["reviewed"] += 1
            confirmed, has_path = assess_project(signals_of(parse_meta(d.get("meta"))), raw_by_project.get(pid, []))
            should_hide = confirmed and not has_path
            if should_hide and pid in active_plans:
                stats["protected_active_plan"] += 1
                should_hide = False
            current = d.get("hidden_reason")
            if should_hide and current is None:
                to_hide.append((pid, str(d.get("name") or "")))
            elif should_hide:
                stats["kept_hidden"] += 1
            elif current == HIDDEN_REASON_ALREADY_LAUNCHED:
                to_unhide.append((pid, str(d.get("name") or "")))

        for pid, name in to_hide:
            db.execute(
                "UPDATE projects SET hidden_reason = ?, hidden_at = ? WHERE id = ? AND hidden_reason IS NULL",
                (HIDDEN_REASON_ALREADY_LAUNCHED, now, pid),
            )
            logger.info("launch_review.project_hidden", project_id=pid, name=name)
        for pid, name in to_unhide:
            db.execute(
                "UPDATE projects SET hidden_reason = NULL, hidden_at = NULL WHERE id = ? AND hidden_reason = ?",
                (pid, HIDDEN_REASON_ALREADY_LAUNCHED),
            )
            logger.info("launch_review.project_unhidden", project_id=pid, name=name)
        db.commit()
        stats["hidden"] = len(to_hide)
        stats["unhidden"] = len(to_unhide)
    except Exception:
        db.rollback()
        raise
