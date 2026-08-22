#!/usr/bin/env python3
# ──────────────────────────────────────────────
# Raw Data Archival Script — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 用法: python scripts/archive_raw_data.py [--dry-run]
# 用途: 按保留期归档/清理采集原始数据
# ──────────────────────────────────────────────

"""
Raw Data Archival Script

按配置保留期清理过期采集数据:
- raw_projects（已处理）: 超过保留期 -> raw_projects_archive
- raw_projects（未过阈值）: 超过更长保留期 -> raw_projects_archive
- project_signals: 超过保留期的信号 -> project_signals_archive
- collection_logs: 超过保留期的日志直接删除 (无归档表)
- 归档表自身: 超过保留期后删除

每次运行都会记入 `archive_runs` 表（trigger=manual），可通过
`GET /api/v1/archive/runs` 或前端 /archive 页查看历史。

用法:
    python scripts/archive_raw_data.py           # 实际归档清理
    python scripts/archive_raw_data.py --dry-run # 只统计不操作
    python scripts/archive_raw_data.py --retention-raw 7 --retention-logs 30
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.archive import RawDataArchiver
from app.db import get_connection, init_db
from app.repositories.archive_runs import TRIGGER_MANUAL


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive old raw collection data")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only count records that would be archived/deleted, do not modify DB",
    )
    parser.add_argument(
        "--retention-raw",
        type=int,
        default=None,
        help="Retention days for processed raw_projects (default: settings.raw_projects_retention_days)",
    )
    parser.add_argument(
        "--retention-signals",
        type=int,
        default=None,
        help="Retention days for project_signals (default: settings.project_signals_retention_days)",
    )
    parser.add_argument(
        "--retention-logs",
        type=int,
        default=None,
        help="Retention days for collection_logs (default: settings.collection_logs_retention_days)",
    )
    parser.add_argument(
        "--retention-unprocessed",
        type=int,
        default=None,
        help=(
            "Retention days for raw_projects that never passed the analysis threshold "
            "(default: settings.unprocessed_raw_retention_days)"
        ),
    )
    args = parser.parse_args()

    try:
        conn = get_connection()
        init_db(conn)
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return 1

    try:
        archiver = RawDataArchiver(
            raw_retention_days=args.retention_raw,
            signals_retention_days=args.retention_signals,
            logs_retention_days=args.retention_logs,
            unprocessed_retention_days=args.retention_unprocessed,
            dry_run=args.dry_run,
        )
        result = archiver.run_and_record(conn, trigger=TRIGGER_MANUAL)
    except Exception as e:
        print(f"❌ Archival failed: {e}")
        return 1
    finally:
        conn.close()

    mode = "DRY RUN" if result.dry_run else "ARCHIVED"
    print(f"\n✅ {mode} complete in {result.duration_ms} ms:")
    print(f"   raw_projects archived (processed):   {result.raw_archived}")
    print(f"   raw_projects archived (unprocessed): {result.unprocessed_archived}")
    print(f"   project_signals archived:            {result.signals_archived}")
    print(f"   collection_logs deleted:             {result.logs_deleted}")
    print(f"   raw archive pruned:                  {result.raw_archive_pruned}")
    print(f"   signals archive pruned:              {result.signals_archive_pruned}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
