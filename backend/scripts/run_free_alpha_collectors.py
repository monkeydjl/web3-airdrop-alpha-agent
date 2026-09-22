"""Run Free Alpha Data Collectors (GitHub Search & Curated Testnets).

Zero-token required. Connects to GitHub public endpoints to discover new
Web3 testnets, faucets, and early airdrop opportunities, persisting them into
raw_projects for the analyzer pipeline.

Usage:
  cd backend
  python scripts/run_free_alpha_collectors.py
  python scripts/run_free_alpha_collectors.py --persist
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from app.collectors.github import GitHubCollector
from app.collectors.github_curated import GitHubCuratedCollector
from app.collectors.persistence import CollectionRepository
from app.db import init_db
from app.pipeline_run import execute_analysis_pipeline


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run free Alpha collectors")
    parser.add_argument("--persist", action="store_true", default=True, help="Save discoveries into database")
    parser.add_argument("--analyze", action="store_true", default=True, help="Run analysis pipeline on discoveries")
    args = parser.parse_args()

    init_db()
    repo = CollectionRepository()

    collectors = [
        ("GitHub Curated Testnets", GitHubCuratedCollector()),
        ("GitHub Open Search", GitHubCollector()),
    ]

    print("=" * 70)
    print("[*] Running Free Web3 Alpha & Testnet Collectors (Zero-Cost / No Token Required)")
    print("=" * 70)

    total_discovered = 0
    total_saved = 0

    for label, collector in collectors:
        print(f"\n[*] Collecting from {label}...")
        try:
            result = await collector.collect()
            print(f"    Status: {result.status} | Items: {len(result.items)}")

            if result.error_message:
                print(f"    Notice: {result.error_message}")

            if args.persist and result.items:
                repo.persist_collection_result(
                    result,
                    source_type=collector.source_type,
                    source_name=collector.source_name,
                )
                print(
                    f"    Persisted into raw_projects: {len(result.items)} items "
                    f"({result.items_new} new, {result.items_duplicate} duplicate)"
                )
                total_saved += len(result.items)

            total_discovered += len(result.items)

            # Display top 5 items
            if result.items:
                print("    Top Discoveries:")
                for it in result.items[:5]:
                    faucet = it.raw_data.get("faucet_url") or "None"
                    print(
                        f"      + {it.name:<22} | Sector: {it.sector:<14} | Stage: {it.stage:<8} "
                        f"| Score: {it.discovery_score:<5} | Faucet: {faucet}"
                    )
        except Exception as e:
            print(f"    Error: {e}")

    print("\n" + "=" * 70)
    print(f"[+] Collection complete! Total: {total_discovered} discoveries processed, {total_saved} persisted.")
    print("=" * 70)

    if args.analyze and total_saved > 0:
        print("\n[*] Running analysis pipeline on unprocessed discoveries...")
        try:
            run_result = await execute_analysis_pipeline()
            status_val = run_result.get("status") if isinstance(run_result, dict) else getattr(run_result, "status", "unknown")
            count_val = len(run_result.get("evaluations", [])) if isinstance(run_result, dict) else len(getattr(run_result, "evaluations", []))
            print(
                f"[+] Pipeline finished: Status={status_val}, "
                f"Evaluated={count_val}"
            )
        except Exception as e:
            print(f"[-] Pipeline run note: {e}")


if __name__ == "__main__":
    asyncio.run(main())
