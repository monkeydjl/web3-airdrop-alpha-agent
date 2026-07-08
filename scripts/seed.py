#!/usr/bin/env python3
# ──────────────────────────────────────────────
# Seed Data Script — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 用法: python scripts/seed.py [--force]
# 用途: 向数据库导入演示种子数据
# ──────────────────────────────────────────────

"""
Seed Data Script

向数据库导入演示种子项目数据，用于 MVP 演示和开发测试。
支持幂等导入：重复运行不会产生重复数据（基于确定性 UUID）。

用法:
    python scripts/seed.py          # 交互式确认后导入
    python scripts/seed.py --force  # 跳过确认直接导入
"""

import argparse
import json
import sys
import os
from pathlib import Path

# 将项目根目录加入 sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# ── 种子数据 ────────────────────────────────
SEED_PROJECTS = [
    {
        "id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
        "name": "LayerX",
        "url": "https://layerx.xyz",
        "sector": "L2",
        "stage": "testnet",
        "raw_signals": {
            "has_points": True,
            "airdrop_hint": True,
            "sources": ["seed"]
        },
        "heat_score": 0.82,
        "narrative_stage": "growth",
        "team_score": 0.72,
        "team_flags": [],
        "token_risk": 0.35,
        "vc_share": 0.25,
        "team_share": 0.20,
        "unlock_pressure": "medium",
    },
    {
        "id": "b2c3d4e5-f6a7-8b9c-0d1e-2f3a4b5c6d7e",
        "name": "ZKPad",
        "url": "https://zkpad.io",
        "sector": "ZK",
        "stage": "testnet",
        "raw_signals": {
            "has_points": True,
            "airdrop_hint": True,
            "sources": ["seed"]
        },
        "heat_score": 0.91,
        "narrative_stage": "early",
        "team_score": 0.85,
        "team_flags": [],
        "token_risk": 0.25,
        "vc_share": 0.30,
        "team_share": 0.15,
        "unlock_pressure": "low",
    },
    {
        "id": "c3d4e5f6-a7b8-9c0d-1e2f-3a4b5c6d7e8f",
        "name": "PrimeStake",
        "url": "https://primestake.finance",
        "sector": "Restaking",
        "stage": "mainnet",
        "raw_signals": {
            "has_points": False,
            "airdrop_hint": True,
            "sources": ["seed"]
        },
        "heat_score": 0.75,
        "narrative_stage": "peak",
        "team_score": 0.60,
        "team_flags": ["anonymous team"],
        "token_risk": 0.55,
        "vc_share": 0.40,
        "team_share": 0.10,
        "unlock_pressure": "high",
    },
    {
        "id": "d4e5f6a7-b8c9-0d1e-2f3a-4b5c6d7e8f9a",
        "name": "InfraChain",
        "url": "https://infrachain.tech",
        "sector": "Infrastructure",
        "stage": "ideation",
        "raw_signals": {
            "has_points": False,
            "airdrop_hint": False,
            "sources": ["seed"]
        },
        "heat_score": 0.45,
        "narrative_stage": "early",
        "team_score": 0.30,
        "team_flags": ["anonymous team", "previous failed project"],
        "token_risk": 0.70,
        "vc_share": 0.50,
        "team_share": 0.25,
        "unlock_pressure": "high",
    },
    {
        "id": "e5f6a7b8-c9d0-1e2f-3a4b-5c6d7e8f9a0b",
        "name": "GameVerse",
        "url": "https://gameverse.gg",
        "sector": "GameFi",
        "stage": "mainnet",
        "raw_signals": {
            "has_points": True,
            "airdrop_hint": False,
            "sources": ["seed"]
        },
        "heat_score": 0.30,
        "narrative_stage": "mature",
        "team_score": 0.55,
        "team_flags": [],
        "token_risk": 0.45,
        "vc_share": 0.35,
        "team_share": 0.30,
        "unlock_pressure": "medium",
    },
]


def main():
    parser = argparse.ArgumentParser(description="Import seed data")
    parser.add_argument("--force", action="store_true", help="Skip confirmation")
    args = parser.parse_args()

    # 连接数据库
    try:
        from app.db import get_connection, init_db
        conn = get_connection()
        init_db(conn)
    except ImportError:
        print("❌ app.db module not found. Run from project root or ensure backend/ is in PYTHONPATH.")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        sys.exit(1)

    # 确认
    if not args.force:
        print(f"Will import {len(SEED_PROJECTS)} seed projects.")
        response = input("Continue? [Y/n]: ").strip().lower()
        if response not in ("", "y", "yes"):
            print("Aborted.")
            sys.exit(0)

    # 导入
    inserted = 0
    updated = 0
    errors = 0

    for project in SEED_PROJECTS:
        try:
            existing = conn.execute(
                "SELECT id FROM projects WHERE id = ?", (project["id"],)
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE projects SET
                        name=?, url=?, sector=?, stage=?, raw_signals=?,
                        updated_at=CURRENT_TIMESTAMP
                    WHERE id=?""",
                    (
                        project["name"], project["url"], project["sector"],
                        project["stage"], json.dumps(project["raw_signals"]),
                        project["id"]
                    )
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO projects
                        (id, name, url, sector, stage, raw_signals, source)
                    VALUES (?, ?, ?, ?, ?, ?, 'seed')""",
                    (
                        project["id"], project["name"], project["url"],
                        project["sector"], project["stage"],
                        json.dumps(project["raw_signals"])
                    )
                )
                inserted += 1
        except Exception as e:
            print(f"❌ Error importing {project['name']}: {e}")
            errors += 1

    conn.commit()
    conn.close()

    print(f"\n✅ Seed complete: {inserted} inserted, {updated} updated, {errors} errors")


if __name__ == "__main__":
    main()
