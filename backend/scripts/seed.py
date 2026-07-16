"""Seed script: insert sample projects into raw_projects and projects tables.

Usage:
    python scripts/seed.py              # default SQLite path from settings
    DATABASE_PATH=./other.db python scripts/seed.py

The script is idempotent: it skips rows with existing dedup_key / project id.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

# Allow running from backend/ root or backend/scripts/
BACKEND_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings
from app.db import get_connection, init_db

SAMPLE_PROJECTS = [
    {
        "name": "Nova L2",
        "url": "https://nova-l2.example.com",
        "sector": "L2",
        "stage": "testnet",
        "signals": {
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "recent_funding": True,
            "high_tvl": False,
            "strong_team": True,
            "active_github": True,
            "hype_social": True,
            "tokenomics_unverified": False,
        },
    },
    {
        "name": "DeFi Vault",
        "url": "https://defi-vault.example.com",
        "sector": "DeFi",
        "stage": "mainnet",
        "signals": {
            "has_testnet": True,
            "has_points_program": False,
            "no_token_yet": True,
            "recent_funding": True,
            "high_tvl": True,
            "strong_team": True,
            "active_github": True,
            "hype_social": False,
            "tokenomics_unverified": True,
        },
    },
    {
        "name": "Pixel Pets",
        "url": "https://pixel-pets.example.com",
        "sector": "Gaming",
        "stage": "testnet",
        "signals": {
            "has_testnet": True,
            "has_points_program": True,
            "no_token_yet": True,
            "recent_funding": False,
            "high_tvl": False,
            "strong_team": False,
            "active_github": False,
            "hype_social": True,
            "tokenomics_unverified": True,
        },
    },
]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dedup_key(name: str) -> str:
    return name.lower().strip().replace(" ", "-")


def _insert_raw_project(conn, source_id: str, project: dict, raw_id: str) -> bool:
    dedup = _dedup_key(project["name"])
    existing = conn.execute(
        "SELECT 1 FROM raw_projects WHERE dedup_key = ?",
        (dedup,),
    ).fetchone()
    if existing:
        print(f"  raw_projects: skip existing dedup_key={dedup}")
        return False

    raw_data = {
        "name": project["name"],
        "url": project["url"],
        "sector": project["sector"],
        "stage": project["stage"],
        "signals": project["signals"],
        "source": "seed",
    }
    conn.execute(
        """
        INSERT INTO raw_projects (raw_id, source_id, dedup_key, raw_data, discovered_at, discovery_score)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (raw_id, source_id, dedup, json.dumps(raw_data, ensure_ascii=False), _now(), 1.0),
    )
    print(f"  raw_projects: inserted {dedup}")
    return True


def _insert_project(conn, raw_id: str, project: dict) -> bool:
    project_id = f"seed-{raw_id}"
    existing = conn.execute(
        "SELECT 1 FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    if existing:
        print(f"  projects: skip existing id={project_id}")
        return False

    merged_name = project["name"]
    merged_url = project.get("url")
    merged_sector = project.get("sector")
    merged_stage = project.get("stage")
    # Compute a simple score from signals for demo purposes.
    signals = project["signals"]
    score = sum(1 for v in signals.values() if v) * 10  # 0-90
    score = max(0, min(100, score + 10))  # bias up slightly
    label = "FARM" if score >= 70 else "WATCH" if score >= 50 else "IGNORE"

    now = _now()
    conn.execute(
        """
        INSERT INTO projects (
            id, name, url, sector, stage, score, label, recommendation,
            confidence, weight_version, source, raw_signals, raw_signals_hash,
            fetched_at, created_at, updated_at, discovery_source, discovered_at,
            auto_discovered, signal_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            merged_name,
            merged_url,
            merged_sector,
            merged_stage,
            score,
            label,
            label,
            0.75,
            "1.0.0",
            "seed",
            json.dumps(signals, ensure_ascii=False),
            hash(json.dumps(signals, sort_keys=True)),
            now,
            now,
            now,
            "seed",
            now,
            0,
            len(signals),
        ),
    )
    print(f"  projects: inserted {project_id} (score={score}, label={label})")
    return True


def _ensure_data_source(conn) -> str:
    source_id = "seed"
    conn.execute(
        """
        INSERT OR IGNORE INTO data_sources (source_id, source_type, source_name, enabled)
        VALUES (?, ?, ?, ?)
        """,
        (source_id, "seed", "Seed Data", 1),
    )
    return source_id


def seed() -> dict:
    """Insert sample projects. Returns counts of inserted rows."""
    print(f"Seeding database: {settings.db_path}")
    init_db()

    conn = get_connection()
    try:
        source_id = _ensure_data_source(conn)
        raw_count = 0
        project_count = 0

        for idx, project in enumerate(SAMPLE_PROJECTS, start=1):
            raw_id = f"seed-{idx:04d}"
            print(f"[{idx}] {project['name']}")
            if _insert_raw_project(conn, source_id, project, raw_id):
                raw_count += 1
            if _insert_project(conn, raw_id, project):
                project_count += 1

        conn.commit()
        print(f"\nDone: inserted {raw_count} raw projects and {project_count} projects.")
        return {"raw_inserted": raw_count, "projects_inserted": project_count}
    finally:
        conn.close()


if __name__ == "__main__":
    # Allow overriding DB path for one-off runs without touching .env
    override = os.environ.get("DATABASE_PATH")
    if override:
        settings.db_path = override
    seed()
