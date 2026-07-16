"""Verify concurrent PostgreSQL schema initialization is serialized."""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=2)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.workers < 4:
        raise ValueError("--workers must be at least 4")
    if args.rounds < 2:
        raise ValueError("--rounds must be at least 2")

    os.environ["DATABASE_URL"] = args.database_url
    from app.db import init_db

    for round_number in range(1, args.rounds + 1):
        barrier = Barrier(args.workers)

        def initialize(_: int, round_barrier: Barrier = barrier) -> None:
            round_barrier.wait()
            init_db()

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            list(executor.map(initialize, range(args.workers)))
        print(f"round={round_number} workers={args.workers} result=PASS")

    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
