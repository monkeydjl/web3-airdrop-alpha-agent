"""Remove denylisted noise from projects + mark matching raw_projects processed.

Does not read or print .env secrets.

  cd backend
  python scripts/purge_noise_projects.py
  python scripts/purge_noise_projects.py --dry-run
"""

from __future__ import annotations

import json
import sys
from contextlib import suppress
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.collectors.noise import is_noise_project, is_noise_raw_project
from app.db import get_connection, init_db, scalar


def main() -> int:
    dry = "--dry-run" in sys.argv
    init_db()
    conn = get_connection()
    deleted = 0
    marked = 0
    try:
        rows = conn.execute("SELECT id, name, sector, label, score FROM projects").fetchall()
        for row in rows:
            d = dict(row)
            name = d.get("name") or ""
            sector = d.get("sector") or ""
            if not is_noise_project(name=name, sector=sector):
                continue
            print(f"{'[dry] ' if dry else ''}DELETE project {name!r} label={d.get('label')} score={d.get('score')}")
            if not dry:
                conn.execute("DELETE FROM projects WHERE id = ?", (d["id"],))
            deleted += 1

        raw_rows = conn.execute("SELECT raw_id, raw_data, source_id, processed FROM raw_projects").fetchall()
        for row in raw_rows:
            d = dict(row)
            if d.get("processed"):
                continue
            raw_data = {}
            with suppress(json.JSONDecodeError):
                raw_data = json.loads(d["raw_data"]) if d.get("raw_data") else {}
            name = str(raw_data.get("name") or "")
            sector = str(raw_data.get("sector") or "")
            if not is_noise_raw_project(name, sector, raw_data):
                continue
            print(f"{'[dry] ' if dry else ''}MARK raw {name!r} source={d.get('source_id')}")
            if not dry:
                conn.execute(
                    "UPDATE raw_projects SET processed = 1, processed_at = CURRENT_TIMESTAMP WHERE raw_id = ?",
                    (d["raw_id"],),
                )
            marked += 1

        if not dry:
            conn.commit()

        remaining = scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone())
        print(f"RESULT: deleted_projects={deleted} marked_raw={marked} projects_remaining={remaining} dry_run={dry}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
