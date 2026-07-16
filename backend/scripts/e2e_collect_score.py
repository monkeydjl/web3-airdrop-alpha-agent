"""End-to-end: multi-source collect + persist + analysis queue /run."""

from __future__ import annotations

import asyncio
import sys
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
for p in (BACKEND, BACKEND.parent):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.defillama import DefiLlamaCollector
from app.collectors.etherscan import EtherscanCollector
from app.collectors.github import GitHubCollector
from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.db import get_connection, init_db, scalar
from app.pipeline_run import execute_analysis_pipeline


async def collect_all() -> dict:
    settings.etherscan_enabled = True
    settings.cryptorank_enabled = True
    init_db()
    repo = CollectionRepository()
    results: dict = {}
    for name, cls in [
        ("defillama", DefiLlamaCollector),
        ("github", GitHubCollector),
        ("cryptorank", CryptoRankCollector),
        ("etherscan", EtherscanCollector),
    ]:
        c = cls()
        if not c.is_enabled():
            results[name] = {"status": "disabled"}
            continue
        r = await c.collect()
        if r.status in ("success", "partial") and r.items:
            repo.persist_collection_result(r, source_type=c.source_type, source_name=c.source_name)
            # Re-queue for scoring so flag/schema fixes apply on re-runs
            conn = get_connection()
            try:
                conn.execute(
                    "UPDATE raw_projects SET processed = 0, processed_at = NULL "
                    "WHERE source_id = ? AND discovery_score >= 0.3",
                    (name,),
                )
                conn.commit()
            finally:
                conn.close()
        scores = [i.discovery_score for i in r.items]
        results[name] = {
            "status": r.status,
            "items": len(r.items),
            "max_score": max(scores) if scores else None,
            "ge_0_3": sum(1 for s in scores if s >= 0.3),
            "samples": [i.name for i in r.items[:5]],
        }
    return results


async def main() -> int:
    print("=== 1) Collect + persist ===")
    cr = await collect_all()
    for k, v in cr.items():
        print(f"  {k}: {v}")

    conn = get_connection()
    try:
        unproc = scalar(
            conn.execute("SELECT COUNT(*) FROM raw_projects WHERE processed = 0 AND discovery_score >= 0.3").fetchone()
        )
        total_raw = scalar(conn.execute("SELECT COUNT(*) FROM raw_projects").fetchone())
        print(f"  raw_projects total={total_raw} unprocessed_ge_0.3={unproc}")
    finally:
        conn.close()

    print("=== 2) Analysis /run (queue, limit=50) ===")
    data = await execute_analysis_pipeline(trigger="manual", limit=50)
    print("  status:", data.get("status"))
    print("  project_count:", data.get("project_count"))
    print("  scored_count:", data.get("scored_count"))
    print("  error_count:", data.get("error_count"))
    print("  top_score:", data.get("top_score"))
    print("  marked_processed:", data.get("marked_processed"))
    tops = data.get("top_projects") or []
    print("  top10 labels:", dict(Counter(p.get("label") for p in tops)))
    for p in tops[:8]:
        print(f"    {p.get('label')} {p.get('score')} {p.get('name')} [{p.get('sector')}]")

    conn = get_connection()
    try:
        rows = conn.execute("SELECT label, COUNT(*) AS c FROM projects GROUP BY label").fetchall()
        print("=== 3) projects by label ===")
        for row in rows:
            d = dict(row)
            print(f"  {d.get('label')}: {d.get('c')}")
        print("  total projects:", scalar(conn.execute("SELECT COUNT(*) FROM projects").fetchone()))
    finally:
        conn.close()
    print("RESULT: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
