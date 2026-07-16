"""Verify PostgreSQL dual-backend wiring.

Requires docker-compose.postgres.yml running on :5433.

  set DATABASE_URL=postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test
  python backend/scripts/verify_postgres.py
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

DEFAULT_URL = "postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test"
os.environ.setdefault("DATABASE_URL", DEFAULT_URL)

from app.agents.base import AgentContext, PipelineState, RawProject
from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.db import backend_name, get_connection, init_db, is_postgres, scalar
from app.metrics import update_db_gauges
from app.pipeline_run import mark_successful_raw_projects
from app.repository import ProjectRepository
from app.utils.normalize import create_dedup_key, generate_deterministic_id


def main() -> int:
    print("database_url set:", bool(settings.database_url))
    print("backend:", backend_name())
    print("is_postgres:", is_postgres())
    if not is_postgres():
        print("FAIL: DATABASE_URL not detected as postgres")
        return 1

    init_db()
    conn = get_connection()
    try:
        # 1) basic CRUD
        conn.execute(
            "INSERT INTO projects (id, name, sector, score, label) VALUES (?, ?, ?, ?, ?)",
            ("pg-smoke-1", "PG Smoke", "L2", 42, "WATCH"),
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, name, score FROM projects WHERE id = ?",
            ("pg-smoke-1",),
        ).fetchone()
        print("crud row:", dict(row) if row else None)

        # 2) relative time SQL rewrite
        n = scalar(
            conn.execute(
                "SELECT COUNT(*) FROM collection_logs WHERE started_at >= datetime('now', '-1 day')"
            ).fetchone()
        )
        print("relative time count:", n)

        # 3) gauges (must not throw)
        update_db_gauges(conn)
        print("gauges: ok")

        # 4) raw_projects mark + repository save
        name = "PG Handoff"
        dedup = create_dedup_key(name, "L2").to_string()
        pid = generate_deterministic_id(create_dedup_key(name, "L2"))
        raw_id = "raw-pg-1"
        conn.execute("DELETE FROM raw_projects WHERE raw_id = ?", (raw_id,))
        conn.execute(
            """
            INSERT INTO raw_projects (
                raw_id, source_id, dedup_key, raw_data, discovered_at,
                processed, discovery_score, project_id
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                raw_id,
                "defillama",
                dedup,
                json.dumps({"name": name, "sector": "L2"}),
                datetime.now(UTC).isoformat(),
                0.8,
                pid,
            ),
        )
        conn.commit()

        repo = CollectionRepository(conn)
        raw = RawProject(
            id=pid,
            name=name,
            sector="L2",
            raw_ids=[raw_id],
            auto_discovered=True,
            discovery_score=0.8,
        )
        from types import SimpleNamespace

        marked = mark_successful_raw_projects(
            [raw],
            [SimpleNamespace(project=SimpleNamespace(id=pid), score=88)],
            repo=repo,
        )
        print("marked_processed:", marked)
        processed = scalar(
            conn.execute(
                "SELECT processed FROM raw_projects WHERE raw_id = ?",
                (raw_id,),
            ).fetchone()
        )
        print("raw processed flag:", processed)

        state = PipelineState(
            project=raw,
            context=AgentContext(run_id="pg-verify"),
            score=88,
            label="FARM",
            confidence=0.9,
            reason=["pg dual backend smoke"],
        )
        ProjectRepository(conn).save(state)
        saved = conn.execute(
            "SELECT score, label FROM projects WHERE id = ?",
            (pid,),
        ).fetchone()
        print("repo save:", dict(saved) if saved else None)

        # cleanup
        conn.execute("DELETE FROM projects WHERE id IN (?, ?)", ("pg-smoke-1", pid))
        conn.execute("DELETE FROM raw_projects WHERE raw_id = ?", (raw_id,))
        conn.commit()

        tables = scalar(
            conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'").fetchone()
        )
        print("public tables:", tables)
    finally:
        conn.close()

    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
