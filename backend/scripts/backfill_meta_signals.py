#!/usr/bin/env python3
"""为历史 projects 行回填 meta.signals。

## 为什么需要这个脚本

`projects.meta.signals` 是重算（`/rescore`、融资编辑后的重评、任何从库里重建
`RawProject` 的路径）唯一的信号来源——`routers/v1/funding._row_to_raw_project`
只读这一处。早于该机制落地的行 `meta` 为 NULL，于是重算时会重建出一个只有
id/name/url/sector/stage 的空壳项目，采集到的信号**全部丢失**。

实测影响（702 行的真实库，全部 meta=NULL）：即使用**未改动的旧代码**重算，
分数均值也会掉 4.30（最差 −34），42% 的项目换标签。这不是评分口径变化，
是重算链路在做有损重建。

好在原始数据还在：`raw_projects.raw_data`（采集器的完整载荷）与
`project_signals`（TVL、链活跃度等结构化信号）都按 dedup_key / project_id 保留着。
本脚本据此重建 `meta.signals`，让重算重新变得无损。

## 用法

    # 先看影响面，不写库
    python scripts/backfill_meta_signals.py --db data/airdrop.db --dry-run

    # 确认后执行（自动先备份到 <db>.bak-<时间戳>）
    python scripts/backfill_meta_signals.py --db data/airdrop.db --apply

    # 回填后再验证重算是否已无损
    python scripts/dual_run_compare.py dump-db /tmp/after_backfill.json data/airdrop.db

只写 `projects.meta` 一列，且只补 `signals` 中缺失的键——已有值一律不覆盖。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.agents.collector import CollectorAgent
from app.services.project_signals import SIGNAL_KEYS, parse_meta
from app.utils.normalize import create_dedup_key


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def collect_sources(conn: sqlite3.Connection) -> tuple[dict[str, list[dict]], dict[str, list[dict]]]:
    """按 project_id 与 dedup_key 归集 raw_projects 载荷。"""
    by_project: dict[str, list[dict]] = defaultdict(list)
    by_dedup: dict[str, list[dict]] = defaultdict(list)
    if not _table_exists(conn, "raw_projects"):
        return by_project, by_dedup
    for row in _rows(conn, "SELECT project_id, dedup_key, source_id, raw_data FROM raw_projects"):
        try:
            payload = json.loads(row["raw_data"]) if row["raw_data"] else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        payload = dict(payload)
        payload.setdefault("source", row["source_id"])
        if row["project_id"]:
            by_project[str(row["project_id"])].append(payload)
        if row["dedup_key"]:
            by_dedup[str(row["dedup_key"])].append(payload)
    return by_project, by_dedup


def collect_structured_signals(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """从 project_signals 提取可直接映射到评分字段的结构化信号。"""
    out: dict[str, dict[str, Any]] = defaultdict(dict)
    if not _table_exists(conn, "project_signals"):
        return out
    for row in _rows(conn, "SELECT project_id, signal_type, signal_data FROM project_signals"):
        pid = str(row["project_id"] or "")
        if not pid:
            continue
        try:
            data = json.loads(row["signal_data"]) if row["signal_data"] else {}
        except (TypeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if row["signal_type"] == "tvl" and data.get("tvl") is not None:
            # 同一项目多条 tvl 记录时取最大（历史快照，规模只会被低估不会被高估）
            prev = out[pid].get("tvl_usd")
            value = float(data["tvl"])
            out[pid]["tvl_usd"] = max(prev, value) if isinstance(prev, (int, float)) else value
    return out


def rebuild_signals(payloads: list[dict], structured: dict[str, Any]) -> dict[str, Any]:
    """用采集器同一套推断逻辑重建信号字典。"""
    signals: dict[str, Any] = {}
    for payload in payloads:
        source = str(payload.get("source") or "unknown")
        try:
            flags = CollectorAgent._infer_airdrop_flags(source, payload)
        except Exception as exc:  # 单条载荷畸形不应中断整库回填
            print(f"warn: 跳过一条 {source} 载荷: {exc}", file=sys.stderr)
            continue
        for key in SIGNAL_KEYS:
            if key not in flags:
                continue
            value = flags[key]
            if value in (None, "", "unknown"):
                continue
            existing = signals.get(key)
            # 布尔取 OR、数值取 max，与 normalize.merge_raw_records 的口径一致
            if isinstance(value, bool):
                signals[key] = bool(existing) or value
            elif isinstance(value, (int, float)) and isinstance(existing, (int, float)):
                signals[key] = max(existing, value)
            elif existing is None:
                signals[key] = value
    for key, value in structured.items():
        if value is not None and signals.get(key) is None:
            signals[key] = value
    if payloads:
        signals["source_count"] = max(1, len({str(p.get("source") or "unknown") for p in payloads}))
    return signals


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="SQLite 库路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计影响面，不写库（默认）")
    parser.add_argument("--apply", action="store_true", help="执行写入（会先自动备份）")
    parser.add_argument("--limit", type=int, default=0, help="只处理前 N 行（调试用）")
    args = parser.parse_args()

    if args.apply and args.dry_run:
        print("--apply 与 --dry-run 互斥", file=sys.stderr)
        return 2
    apply = args.apply

    db_path = Path(args.db)
    if not db_path.is_file():
        print(f"找不到数据库: {db_path}", file=sys.stderr)
        return 2

    if apply:
        stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        backup = db_path.with_suffix(db_path.suffix + f".bak-{stamp}")
        shutil.copy(db_path, backup)
        print(f"已备份 → {backup}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        by_project, by_dedup = collect_sources(conn)
        structured = collect_structured_signals(conn)

        sql = "SELECT id, name, sector, stage, url, meta FROM projects ORDER BY id"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        projects = _rows(conn, sql)

        stats = {"total": len(projects), "already": 0, "no_source": 0, "filled": 0}
        key_counts: dict[str, int] = defaultdict(int)
        updates: list[tuple[str, str]] = []

        for project in projects:
            meta = parse_meta(project.get("meta"))
            existing = meta.get("signals") if isinstance(meta.get("signals"), dict) else {}

            payloads = by_project.get(str(project["id"])) or []
            if not payloads:
                dedup = create_dedup_key(project.get("name") or "", project.get("sector")).to_string()
                payloads = by_dedup.get(dedup) or []
            if not payloads and not structured.get(str(project["id"])):
                stats["no_source"] += 1
                continue

            rebuilt = rebuild_signals(payloads, structured.get(str(project["id"]), {}))
            # 只补缺失键，绝不覆盖已有值
            merged = dict(rebuilt)
            merged.update({k: v for k, v in existing.items() if v is not None})
            added = {k for k in merged if k not in existing}
            if not added:
                stats["already"] += 1
                continue
            for key in added:
                key_counts[key] += 1
            stats["filled"] += 1
            meta["signals"] = merged
            updates.append((json.dumps(meta, ensure_ascii=False), str(project["id"])))

        print("=" * 62)
        print(f"projects 总行数        : {stats['total']}")
        print(f"可回填                 : {stats['filled']}")
        print(f"已有信号、无需变更     : {stats['already']}")
        print(f"找不到原始记录         : {stats['no_source']}")
        if key_counts:
            print()
            print("按字段统计新增覆盖数:")
            for key in sorted(key_counts, key=lambda k: -key_counts[k]):
                print(f"  {key:<28} {key_counts[key]:>6}")
        print("=" * 62)

        if not apply:
            print("这是预演（未写库）。确认无误后加 --apply 执行。")
            return 0

        conn.executemany("UPDATE projects SET meta = ? WHERE id = ?", updates)
        conn.commit()
        print(f"已写入 {len(updates)} 行的 meta.signals。")
        print("建议接着跑：python scripts/dual_run_compare.py dump-db /tmp/after.json " + str(db_path))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
