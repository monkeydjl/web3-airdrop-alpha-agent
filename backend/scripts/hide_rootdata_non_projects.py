"""Hide projects that exist only because RootData returned a person / VC / social entry.

RootData `/open/ser_inv` mixes projects with people (type=3), institutions (type=2)
and social accounts / lists (type=5). Before the 2026-10-08 filter those entries
were ingested as projects (e.g. "Deirdre Connolly", "airdropkorea").

Hide, don't delete (same rule as launch_review):
  - project hidden with hidden_reason="not_a_project" when **every** raw row behind
    it is a RootData non-project entry — a project corroborated by any real row
    (another source, or a RootData type=1 row) is left alone;
  - those raw rows are quarantined so a later bulk release cannot bring them back.

Projects the user manually unhid (unhidden_by_user_at set) are skipped.
Idempotent. Does not read or print .env secrets.

  cd backend
  python scripts/hide_rootdata_non_projects.py --dry-run
  python scripts/hide_rootdata_non_projects.py
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.collectors.noise import is_rootdata_non_project
from app.db import get_connection, init_db

HIDDEN_REASON_NOT_A_PROJECT = "not_a_project"


def plan(conn) -> tuple[list[tuple[str, str]], list[str]]:
    """Return ([(project_id, name)] to hide, [raw_id] to quarantine)."""
    rows_by_project: dict[str, list[tuple[str, str, bool, bool]]] = defaultdict(list)
    for row in conn.execute("SELECT raw_id, source_id, raw_data, project_id, quarantined FROM raw_projects"):
        d = dict(row)
        if not d.get("project_id"):
            continue
        raw_data: dict = {}
        with suppress(json.JSONDecodeError, TypeError):
            raw_data = json.loads(d["raw_data"]) if d.get("raw_data") else {}
        non_project = d["source_id"] == "rootdata" and is_rootdata_non_project(raw_data)
        rows_by_project[str(d["project_id"])].append(
            (str(d["raw_id"]), str(d["source_id"]), non_project, bool(d.get("quarantined")))
        )

    to_hide: list[tuple[str, str]] = []
    to_quarantine: list[str] = []
    for pid, raws in rows_by_project.items():
        if not raws or not all(non_project for _, _, non_project, _ in raws):
            continue
        to_quarantine.extend(raw_id for raw_id, _, _, quarantined in raws if not quarantined)
        proj = conn.execute(
            "SELECT name, hidden_reason, unhidden_by_user_at FROM projects WHERE id = ?", (pid,)
        ).fetchone()
        if proj is None:
            continue
        p = dict(proj)
        if p.get("hidden_reason") is None and p.get("unhidden_by_user_at") is None:
            to_hide.append((pid, str(p.get("name") or "")))
    return to_hide, to_quarantine


def main() -> int:
    dry = "--dry-run" in sys.argv
    init_db()
    conn = get_connection()
    try:
        to_hide, to_quarantine = plan(conn)
        now = datetime.now(UTC).isoformat()
        for pid, name in to_hide:
            print(f"{'[dry] ' if dry else ''}HIDE project {name!r} ({pid})")
            if not dry:
                conn.execute(
                    "UPDATE projects SET hidden_reason = ?, hidden_at = ? WHERE id = ? AND hidden_reason IS NULL",
                    (HIDDEN_REASON_NOT_A_PROJECT, now, pid),
                )
        for raw_id in to_quarantine:
            if not dry:
                conn.execute(
                    "UPDATE raw_projects SET quarantined = 1, quarantine_reason = ?, processed = 1 WHERE raw_id = ?",
                    ("non_project:rootdata:backfill", raw_id),
                )
        if not dry:
            conn.commit()
        print(f"RESULT: hidden_projects={len(to_hide)} quarantined_raw={len(to_quarantine)} dry_run={dry}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
