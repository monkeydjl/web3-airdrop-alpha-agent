"""把既有 `projects` 行的 ID 钉成 backfill 别名。

项目身份改造（`app/identity.py`）后，`dedup_keys` 成为别名表。存量项目没有别名，
虽然旧的 `uuid5("name::sector")` 兜底仍能解析出同样的 ID，但只要项目改名或赛道
写法变化就会分裂出新行。本脚本把每一行既有 projects 的 `(name, sector)`
明确钉到它当前的 `project_id` 上（source=backfill），历史评分与 project_history
从此有稳定的锚点。

冲突只报告、不合并：
- 同一别名键指向别的 project_id（已有人工/自动别名）→ `alias_points_elsewhere`
- 多个 projects 行共享同一别名键（存量重复行）→ `multiple_projects_share_key`

合并重复项目是另一件事，不在本脚本范围内。脚本只写 `dedup_keys`，不删不改任何
projects 行。不读取、不打印 .env 或任何密钥。

    cd backend
    python scripts/backfill_project_aliases.py              # dry-run，只出报告
    python scripts/backfill_project_aliases.py --apply      # 真正写库
    python scripts/backfill_project_aliases.py --json       # JSON 报告（便于归档）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.db import init_db
from app.identity import backfill_project_aliases


def _print_report(payload: dict, *, sample: int = 20) -> None:
    mode = "APPLY" if payload["apply"] else "DRY-RUN"
    print(f"[{mode}] 扫描 {payload['scanned']} 个 projects 行")
    print(f"  已钉住（别名已指向自身）: {payload['already_pinned']}")
    print(f"  可新增 backfill 别名     : {payload['candidate_count']}")
    print(f"  冲突（不写库）           : {payload['conflict_count']}")
    if payload["apply"]:
        print(f"  实际写入                 : {payload['applied']}")

    if payload["conflicts"]:
        print("\n冲突明细（只报告，不自动合并）:")
        for item in payload["conflicts"][:sample]:
            print(f"  - {json.dumps(item, ensure_ascii=False)}")

    if payload["candidates"]:
        print("\n前几个可新增别名:")
        for item in payload["candidates"][:sample]:
            print(f"  - {item['dedup_key']} -> {item['project_id']} ({item['name']})")

    if not payload["apply"] and payload["candidate_count"]:
        print("\n这是 dry-run，没有写库。确认报告后加 --apply 执行。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="把既有 projects 行钉成 backfill 身份别名（默认 dry-run）")
    parser.add_argument("--apply", action="store_true", help="真正写入 dedup_keys（默认只出报告）")
    parser.add_argument("--limit", type=int, default=None, help="最多扫描多少条 projects 行")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON 报告")
    args = parser.parse_args(argv)

    init_db()
    report = backfill_project_aliases(apply=args.apply, limit=args.limit)
    payload = report.to_dict(sample=100_000)

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_report(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
