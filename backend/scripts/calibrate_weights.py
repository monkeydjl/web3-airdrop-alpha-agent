"""权重校准 CLI（Weight Calibration Script）。

Usage:
    # 门禁报告（不搜索，不改生产权重）
    python scripts/calibrate_weights.py

    # 执行搜索并记录候选到 weight_changelog
    python scripts/calibrate_weights.py --search

    # 指定 DB 路径
    DATABASE_PATH=./other.db python scripts/calibrate_weights.py --search

Reference:
- WEIGHT_CALIBRATION.md §4.3 离线流程
- V2_TASKS.md C2
"""

from __future__ import annotations

import sys
from pathlib import Path

# Allow running from backend/ root or backend/scripts/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

import argparse

from app.calibration import format_report, run_calibration
from app.db import get_connection


def main() -> int:
    parser = argparse.ArgumentParser(description="权重校准脚本：门禁检查 + 可选搜索")
    parser.add_argument(
        "--search",
        action="store_true",
        help="执行权重搜索并记录候选到 weight_changelog（默认仅门禁报告）",
    )
    parser.add_argument(
        "--triggered-by",
        default="human",
        help="触发者标识（human / scheduled_job）",
    )
    args = parser.parse_args()

    conn = get_connection()
    try:
        report = run_calibration(
            conn,
            search=args.search,
            triggered_by=args.triggered_by,
        )
    finally:
        conn.close()

    print(format_report(report))

    # 退出码：门禁未通过返回 1，通过返回 0
    return 0 if report.gate.passed else 1


if __name__ == "__main__":
    sys.exit(main())
