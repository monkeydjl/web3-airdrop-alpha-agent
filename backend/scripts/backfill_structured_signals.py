#!/usr/bin/env python3
"""为存量 projects 行回填结构化 Anti-PUA 信号（meta.signals）。

## 为什么需要这个脚本

2026-09-27 起，`app/opportunity/evidence.py` 的 fatigue/friction 输入从
description/sector 文本匹配切换为三个结构化信号键（opportunity 是非权威
Shadow 旁路，主评分 score-v1.4 不受影响）：

- ``points_season_count``  积分季数（int, 1-10）
- ``tge_clarity``          TGE 时间清晰度（confirmed_quarter / vague_soon / unannounced）
- ``is_perp``              是否永续合约/衍生品协议（bool）

切换后存量行这三个键全部缺失 → 一律回退保守默认档（season=1、unannounced、
False），旧文本匹配"碰巧"得出的 season=3 / is_perp=True 不再生效。本脚本
用**与旧逻辑相同但更严格的词表**从 description/sector 一次性提取候选值写回，
让旁路模型恢复完整输入。

## 提取规则与人工审核清单

三类提取置信度不同，处理方式不同：

1. ``is_perp``（高置信）——沿用评分线已有的 `agents.risk.is_perp_dex` 判定
   （perp dex / perpetual / derivative，且**不**匹配项目名）。自动写入，
   无需审核：主评分 risk 子分本来就在用同一判定器。
2. ``tge_clarity``（中置信）——仅当 description 明确出现 "confirmed" +
   (季度词 或 "tge"/"token generation") 组合时写 confirmed_quarter；
   其余一律不写（保留 evidence.py 的 unannounced 默认）。自动写入。
3. ``points_season_count``（低置信）——"season N" / "season N-B" /
   "sN" 词形匹配。误报面最大（"s3x" 类子串已用词边界正则排除，但
   "support 3" 这类描述仍可能误伤），因此**只写入审核清单 CSV，
   不写库**；运营核对后手工 UPDATE 或二次运行 --apply-review。

## 用法

    # 预演：不写库，只打印影响面
    python scripts/backfill_structured_signals.py --db data/airdrop.db --dry-run

    # 执行自动写入（is_perp + tge_clarity；自动先备份 .bak-<时间戳>）
    python scripts/backfill_structured_signals.py --db data/airdrop.db --apply

    # 人工审核清单（两档都会生成）：
    #   <db>.review-<stamp>.csv        低置信 season 候选（不写库，人工核对）
    #   <db>.manifest-<stamp>.json     写入清单 + 提取依据，供回溯/审计
    # 回滚 = 恢复 .bak 备份，或按 manifest 对受影响行反向还原 meta 列。

只写 projects.meta 一列的 signals 三个键，且**只补缺失键、已有值绝不覆盖**。
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.project_signals import parse_meta
from app.services.structured_signals import extract_is_perp as _extract_is_perp
from app.services.structured_signals import extract_season_count, extract_tge_clarity

REVIEW_HEADERS = ("project_id", "name", "matched_text", "candidate_season", "confidence_note")

# 词形与置信度规则的唯一来源是 services.structured_signals —— 本脚本与
# 采集侧（agents.collector._infer_airdrop_flags）共用同一实现，防止两套
# 词表漂移导致同一项目在回填与采集之间得出不同结论。
MAX_SEASON = 10  # 与 evidence._signal_season_count / structured_signals 一致


def _project_text(project: dict[str, Any], signals: dict[str, Any]) -> str:
    """拼接提取用文本：meta.signals.description（存储位置）+ sector。

    projects 表没有 description 列——描述作为信号存在 meta.signals 里
    （services.project_signals.SIGNAL_KEYS）。提取以 signals 里的值为准,
    缺失时回退 meta 顶层的 description（个别旧写入路径）。
    """
    description = signals.get("description") or project.get("description") or ""
    return f"{description} {project.get('sector') or ''}".lower()


def extract_is_perp(project: dict[str, Any], signals: dict[str, Any] | None = None) -> bool:
    """沿用 structured_signals 的高置信 perp 判定（与主评分 is_perp_dex 同词形口径）。"""
    sig = signals or {}
    return _extract_is_perp(
        str(project.get("sector") or ""),
        str(sig.get("description") or project.get("description") or ""),
    )


def derive_candidates(project: dict[str, Any], signals: dict[str, Any] | None = None) -> dict[str, Any]:
    """汇总一个项目的候选信号。只含"有信息量且达到写入置信度"的键。"""
    sig = signals or {}
    text = _project_text(project, sig)
    candidates: dict[str, Any] = {}
    if extract_is_perp(project, sig):
        candidates["is_perp"] = True
    tge = extract_tge_clarity(text)
    if tge:
        candidates["tge_clarity"] = tge
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", required=True, help="SQLite 库路径")
    parser.add_argument("--dry-run", action="store_true", help="只统计影响面，不写库（默认）")
    parser.add_argument("--apply", action="store_true", help="执行自动写入（会先自动备份）")
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

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup: Path | None = None
    if apply:
        backup = db_path.with_suffix(db_path.suffix + f".bak-{stamp}")
        shutil.copy(db_path, backup)
        print(f"已备份 → {backup}")

    review_path = db_path.with_suffix(db_path.suffix + f".review-{stamp}.csv")
    manifest_path = db_path.with_suffix(db_path.suffix + f".manifest-{stamp}.json")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        sql = "SELECT id, name, sector, stage, url, meta FROM projects ORDER BY id"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        projects = [dict(r) for r in conn.execute(sql).fetchall()]

        stats = {"total": len(projects), "auto_write": 0, "no_change": 0, "review_only": 0}
        key_counts: Counter[str] = Counter()
        updates: list[tuple[str, str, str, Any]] = []  # (meta_json, project_id, keys_joined, old_meta_json)
        review_rows: list[tuple[str, str, str, int, str]] = []

        for project in projects:
            meta = parse_meta(project.get("meta"))
            raw_signals = meta.get("signals")
            signals: dict[str, Any] = raw_signals if isinstance(raw_signals, dict) else {}

            candidates = derive_candidates(project, signals)
            # 只补缺失键，绝不覆盖已有值（与 backfill_meta_signals 同一口径）
            additions = {k: v for k, v in candidates.items() if k not in signals}

            # 低置信 season 候选：一律只进审核清单，不写库
            text = _project_text(project, signals)
            season = extract_season_count(text)
            if season is not None and "points_season_count" not in signals:
                review_rows.append(
                    (
                        str(project["id"]),
                        str(project.get("name") or ""),
                        season[1],
                        season[0],
                        "词形命中;请人工核对季数后手工写入或用 --apply-review",
                    )
                )

            if not additions:
                if season is not None and "points_season_count" not in signals:
                    stats["review_only"] += 1
                else:
                    stats["no_change"] += 1
                continue

            merged = dict(signals)
            merged.update(additions)
            meta["signals"] = merged
            updates.append(
                (
                    json.dumps(meta, ensure_ascii=False),
                    str(project["id"]),
                    ",".join(sorted(additions)),
                    json.dumps(signals.get("description"), ensure_ascii=False) if signals.get("description") else None,
                )
            )
            for key in additions:
                key_counts[key] += 1
            stats["auto_write"] += 1

        # 人工审核清单（低置信 season 候选）
        with review_path.open("w", newline="", encoding="utf-8-sig", errors="replace") as stream:
            writer = csv.writer(stream)
            writer.writerow(REVIEW_HEADERS)
            writer.writerows(review_rows)

        # 写入清单 + 提取依据（审计/回溯用）
        manifest = {
            "script": "backfill_structured_signals",
            "created_at": datetime.now(UTC).isoformat(),
            "db": str(db_path),
            "backup": str(backup) if backup else None,
            "mode": "apply" if apply else "dry-run",
            "stats": stats,
            "key_counts": dict(key_counts),
            "updates": [
                {"project_id": pid, "added_keys": keys, "new_meta": new_meta, "old_meta": old_meta}
                for new_meta, pid, keys, old_meta in updates
            ],
            "review_csv": str(review_path),
            "review_row_count": len(review_rows),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        print("=" * 62)
        print(f"projects 总行数            : {stats['total']}")
        print(f"自动写入（is_perp/tge）    : {stats['auto_write']}")
        print(f"仅入审核清单（season）     : {stats['review_only']}")
        print(f"无需变更                   : {stats['no_change']}")
        if key_counts:
            print()
            print("按字段统计自动写入数:")
            for key in sorted(key_counts, key=lambda k: -key_counts[k]):
                print(f"  {key:<24} {key_counts[key]:>6}")
        print()
        print(f"人工审核清单: {review_path}（{len(review_rows)} 行,均未写库）")
        print(f"写入清单/审计: {manifest_path}")
        print("=" * 62)

        if not apply:
            print("这是预演（未写库）。确认后加 --apply 执行自动写入部分。")
            return 0

        conn.executemany("UPDATE projects SET meta = ? WHERE id = ?", [(u[0], u[1]) for u in updates])
        conn.commit()
        print(f"已写入 {len(updates)} 行的 meta.signals（season 候选仍在审核清单里,未写库）。")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
