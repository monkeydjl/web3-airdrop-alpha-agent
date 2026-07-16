"""CLI for quarantine management.

cd backend
python scripts/quarantine_cli.py list
python scripts/quarantine_cli.py count
python scripts/quarantine_cli.py add <raw_id> <reason>
python scripts/quarantine_cli.py release <raw_id>
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

from app.db import init_db
from app.quarantine import list_quarantined, quarantine_count, quarantine_raw, release_quarantine


def main() -> int:
    init_db()
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    cmd = args[0]
    if cmd == "count":
        print("quarantined:", quarantine_count())
        return 0
    if cmd == "list":
        items = list_quarantined(limit=50)
        print(f"count={quarantine_count()} showing={len(items)}")
        for it in items:
            name = ""
            with suppress(json.JSONDecodeError):
                name = (json.loads(it.get("raw_data") or "{}") or {}).get("name", "")
            print(f"  {it['raw_id']}  {name}  reason={it.get('quarantine_reason')}")
        return 0
    if cmd == "add" and len(args) >= 3:
        raw_id, reason = args[1], " ".join(args[2:])
        ok = quarantine_raw(raw_id, reason)
        print("ok" if ok else "not_found")
        return 0 if ok else 1
    if cmd == "release" and len(args) >= 2:
        ok = release_quarantine(args[1])
        print("ok" if ok else "not_found")
        return 0 if ok else 1

    print("Unknown command", file=sys.stderr)
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
