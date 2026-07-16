"""Seed demo feedback rows for calibration testing (not production labels).

cd backend
python scripts/seed_demo_feedback.py
"""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.db import get_connection, init_db, scalar

SIGNALS = ("useful", "useless", "wrong_label", "correct_outcome")
OUTCOMES = (None, "airdropped", "not_airdropped", None)


def main() -> int:
    init_db()
    conn = get_connection()
    try:
        projects = conn.execute("SELECT id, label FROM projects ORDER BY score DESC LIMIT 40").fetchall()
        if not projects:
            print("No projects; run e2e-collect first")
            return 1
        n = 0
        for i, row in enumerate(projects):
            d = dict(row)
            signal = SIGNALS[i % len(SIGNALS)]
            outcome = OUTCOMES[i % len(OUTCOMES)]
            conn.execute(
                """
                INSERT INTO feedback (project_id, user_id, signal, note, outcome)
                VALUES (?, ?, ?, ?, ?)
                """,
                (d["id"], "demo-user", signal, f"demo feedback {i}", outcome),
            )
            n += 1
        conn.commit()
        total = scalar(conn.execute("SELECT COUNT(*) FROM feedback").fetchone())
        print(f"inserted={n} feedback_total={total}")
    finally:
        conn.close()
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
