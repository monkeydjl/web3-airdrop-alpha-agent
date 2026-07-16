"""Feedback sample snapshot for weight calibration (WEIGHT_CALIBRATION.md).

Does not change weights. Prints counts only (no secrets).

  cd backend
  python scripts/feedback_snapshot.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.db import get_connection, init_db, scalar

# First calibration gate (ADR-006 / WEIGHT_CALIBRATION.md)
MIN_SAMPLES = 200


def main() -> int:
    init_db()
    conn = get_connection()
    try:
        total = scalar(conn.execute("SELECT COUNT(*) FROM feedback").fetchone())
        by_signal = conn.execute("SELECT signal, COUNT(*) AS c FROM feedback GROUP BY signal").fetchall()
        with_outcome = scalar(
            conn.execute("SELECT COUNT(*) FROM feedback WHERE outcome IS NOT NULL AND outcome != ''").fetchone()
        )
        wrong_label = scalar(conn.execute("SELECT COUNT(*) FROM feedback WHERE signal = 'wrong_label'").fetchone())
        projects = scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone())
        farm = scalar(conn.execute("SELECT COUNT(*) FROM projects WHERE label = 'FARM'").fetchone())
    finally:
        conn.close()

    print("=== Feedback calibration snapshot ===")
    print(f"projects_total: {projects}")
    print(f"projects_farm:  {farm}")
    print(f"feedback_total: {total}")
    print(f"feedback_with_outcome: {with_outcome}")
    print(f"feedback_wrong_label:  {wrong_label}")
    print("by_signal:")
    for row in by_signal:
        d = dict(row)
        print(f"  {d.get('signal')}: {d.get('c')}")
    ready = int(total) >= MIN_SAMPLES
    print(f"calibration_ready (>= {MIN_SAMPLES}): {ready}")
    if not ready:
        print(f"need {max(0, MIN_SAMPLES - int(total))} more feedback samples before weight search")
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
