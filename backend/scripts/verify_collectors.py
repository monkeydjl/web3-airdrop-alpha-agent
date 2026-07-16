"""Real-network verification for configured collectors.

Keys load from repo-root .env or backend/.env (never printed).

  cd backend
  python scripts/verify_collectors.py
  python scripts/verify_collectors.py --persist
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.collectors.coingecko import CoinGeckoCollector
from app.collectors.cryptorank import CryptoRankCollector
from app.collectors.etherscan import EtherscanCollector
from app.collectors.github import GitHubCollector
from app.collectors.persistence import CollectionRepository
from app.config import settings
from app.db import init_db


def _mask(ok: bool) -> str:
    return "SET" if ok else "MISSING"


def _force_enable_flags() -> None:
    """For verification only: if a key is present, enable the source flag."""
    if settings.github_token:
        settings.github_enabled = True
    if settings.coingecko_api_key:
        settings.coingecko_enabled = True
    if settings.etherscan_api_key:
        settings.etherscan_enabled = True
    if settings.cryptorank_api_key:
        settings.cryptorank_enabled = True


async def _collect(name: str, collector, key_set: bool, persist: bool) -> dict:
    out: dict = {
        "source": name,
        "key": _mask(key_set),
        "enabled": collector.is_enabled(),
    }
    if not collector.is_enabled():
        out["status"] = "skipped"
        out["reason"] = "disabled or missing key"
        return out

    if hasattr(collector, "health_check"):
        try:
            health = await collector.health_check()
            out["health"] = health.get("status")
            if health.get("search_remaining") is not None:
                out["search_remaining"] = health.get("search_remaining")
            if health.get("error"):
                out["health_error"] = str(health.get("error"))[:200]
        except Exception as e:
            out["health"] = "error"
            out["health_error"] = str(e)[:200]

    try:
        result = await collector.collect()
    except Exception as e:
        out["status"] = "error"
        out["error"] = str(e)[:300]
        return out

    out["status"] = result.status
    out["items"] = len(result.items)
    if result.error_message:
        out["error"] = result.error_message[:300]
    if result.items:
        top = sorted(result.items, key=lambda x: x.discovery_score, reverse=True)[:5]
        out["samples"] = [{"name": (i.name or "")[:80], "score": i.discovery_score, "sector": i.sector} for i in top]
    if persist and result.status in ("success", "partial") and result.items:
        CollectionRepository().persist_collection_result(
            result,
            source_type=collector.source_type,
            source_name=collector.source_name,
        )
        out["persisted"] = True
    return out


async def main() -> int:
    persist = "--persist" in sys.argv
    _force_enable_flags()

    print("=== Collector verification (secrets never printed) ===")
    print(f"github:    key={_mask(bool(settings.github_token))} enabled={settings.github_enabled}")
    print(f"coingecko: key={_mask(bool(settings.coingecko_api_key))} enabled={settings.coingecko_enabled}")
    print(f"etherscan: key={_mask(bool(settings.etherscan_api_key))} enabled={settings.etherscan_enabled}")
    print(f"cryptorank:key={_mask(bool(settings.cryptorank_api_key))} enabled={settings.cryptorank_enabled}")
    print(f"persist={persist}")
    print()

    if persist:
        init_db()

    jobs = [
        ("github", GitHubCollector(), bool(settings.github_token)),
        ("coingecko", CoinGeckoCollector(), bool(settings.coingecko_api_key)),
        ("etherscan", EtherscanCollector(), bool(settings.etherscan_api_key)),
        ("cryptorank", CryptoRankCollector(), bool(settings.cryptorank_api_key)),
    ]

    results = []
    for name, collector, key_set in jobs:
        results.append(await _collect(name, collector, key_set, persist))

    ok = 0
    hard_fail = False
    for block in results:
        print(f"--- {block['source']} ---")
        for k, v in block.items():
            if k != "source":
                print(f"  {k}: {v}")
        print()
        if block.get("status") in ("success", "partial"):
            ok += 1
        if block.get("key") == "SET" and block.get("status") == "error":
            hard_fail = True

    print(f"RESULT: {ok}/{len(results)} collectors OK")
    if not settings.etherscan_enabled and settings.etherscan_api_key:
        print("TIP: keep ETHERSCAN_ENABLED=true in .env for scheduled/API runs.")
    if not settings.cryptorank_enabled and settings.cryptorank_api_key:
        print("TIP: keep CRYPTORANK_ENABLED=true in .env for scheduled/API runs.")
    return 1 if hard_fail else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
