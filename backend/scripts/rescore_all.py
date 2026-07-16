"""Re-score all projects with current rules, restoring meta.signals.

cd backend
python scripts/rescore_all.py
"""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
for p in (BACKEND, ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.agents.base import AgentContext, RawProject
from app.agents.collector import CollectorAgent
from app.agents.orchestrator_simple import SimpleOrchestrator
from app.collectors.noise import is_noise_project
from app.db import get_connection, init_db, scalar
from app.repository import ProjectRepository
from app.services.project_signals import apply_signals_to_kwargs


async def main() -> int:
    init_db()
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, name, url, sector, stage, source, meta FROM projects").fetchall()
    finally:
        conn.close()

    projects: list[RawProject] = []
    skipped = 0
    for row in rows:
        d = dict(row)
        name = d.get("name") or ""
        sector = d.get("sector")
        if is_noise_project(name=name, sector=sector or ""):
            ProjectRepository().delete_by_id(d["id"])
            skipped += 1
            continue
        stage = d.get("stage") or "mainnet"
        source = d.get("source") or "unknown"
        # Restore saved signals first, then fill gaps via inference
        saved = apply_signals_to_kwargs(d.get("meta"))
        flags = CollectorAgent._infer_airdrop_flags(
            source.split(",")[0] if source else "defillama",
            {
                "name": name,
                "sector": sector,
                "stage": stage,
                "url": d.get("url"),
                **{k: v for k, v in saved.items() if v not in (None, "", [], "unknown")},
            },
        )
        # Prefer explicit saved funding/signals over pure inference
        merged = {**flags, **saved}
        for k in ("has_testnet", "has_points_program", "no_token_yet", "recent_funding"):
            if k in saved:
                merged[k] = saved[k]
            elif k in flags:
                merged[k] = flags[k]

        kwargs = {
            "id": d["id"],
            "name": name,
            "url": d.get("url"),
            "sector": sector,
            "stage": stage,
            "source": source,
            "auto_discovered": True,
        }
        # only pass known RawProject fields
        field_names = {field.name for field in RawProject.__dataclass_fields__.values()}
        for k, v in merged.items():
            if k in field_names and k not in kwargs:
                kwargs[k] = v
        projects.append(RawProject(**kwargs))

    print(f"rescoring {len(projects)} (deleted_noise={skipped})")
    orch = SimpleOrchestrator()
    ctx = AgentContext(run_id="rescore-v1.4")
    counts = orch._calculate_sector_counts(projects)
    labels: Counter[str] = Counter()
    farms: list[tuple[int, str, str | None]] = []

    for p in projects:
        state = await orch._run_single_project(p, ctx, counts)
        labels[state.label or "?"] += 1
        if state.label == "FARM":
            farms.append((state.score or 0, p.name, p.sector))
        ProjectRepository().save(state)

    farms.sort(reverse=True)
    print("labels:", dict(labels))
    print("FARM top:")
    for score, name, sector in farms[:12]:
        print(f"  {score} {name} [{sector}]")

    conn = get_connection()
    try:
        total = scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone())
        print("projects remaining:", total)
    finally:
        conn.close()
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
