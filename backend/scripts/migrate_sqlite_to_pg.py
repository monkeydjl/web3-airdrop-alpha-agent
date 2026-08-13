#!/usr/bin/env python3
"""SQLite → PostgreSQL 一次性数据迁移脚本。

用法：
    # 先启动 PG（如 docker compose -f docker-compose.postgres.yml up -d）
    # 再执行：
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite-path data/airdrop.db \
        --pg-dsn postgresql://airdrop:airdrop_test@127.0.0.1:5433/airdrop_test

    # 干跑（不写数据，只输出统计）：
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite-path data/airdrop.db \
        --pg-dsn postgresql://... --dry-run

迁移完成后：
    python scripts/verify_postgres.py  # 冒烟验证
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import UTC, datetime
from typing import Any

try:
    import psycopg
    from psycopg.rows import dict_row
except ImportError:
    print("psycopg not installed. Run: pip install psycopg[binary]", file=sys.stderr)
    sys.exit(1)


# ── 表迁移顺序（尊重逻辑依赖，无 FK 约束但保持语义顺序）──
TABLE_ORDER = [
    "projects",
    "raw_projects",
    "project_signals",
    "collection_logs",
    "data_sources",
    "logs",
    "events",
    "feedback",
    "interactions",
    "raw_projects_archive",
    "project_signals_archive",
    "opportunity_evidence",
    "opportunity_assessments",
    "opportunity_economic_snapshots",
]

# AUTOINCREMENT → SERIAL 的表（迁移后需 setval 重置序列）
SERIAL_TABLES = {"logs", "feedback", "events", "interactions"}

# TIMESTAMP → TIMESTAMPTZ 的列（SQLite naive → PG 带时区）
TIMESTAMPTZ_COLUMNS: dict[str, set[str]] = {
    "interactions": {"outcome_observed_at", "created_at", "updated_at"},
    "opportunity_evidence": {"observed_at", "effective_at", "expires_at", "created_at"},
    "opportunity_assessments": {"scored_at", "review_at", "expires_at", "created_at"},
    "opportunity_economic_snapshots": {"collected_at"},
}

# REAL → DOUBLE PRECISION（无需转换，仅记录）
REAL_TABLES = {
    "projects",
    "raw_projects",
    "raw_projects_archive",
    "project_signals",
    "project_signals_archive",
    "interactions",
    "opportunity_assessments",
}


def get_sqlite_tables(conn: sqlite3.Connection) -> list[str]:
    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r[0] for r in cur.fetchall()]


def get_sqlite_columns(conn: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    cur = conn.execute(f"PRAGMA table_info([{table}])")
    return [{"name": r[1], "type": r[2], "notnull": r[3], "default": r[4], "pk": r[5]} for r in cur.fetchall()]


def get_sqlite_row_count(conn: sqlite3.Connection, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]  # noqa: S608


def pg_type_for(sqlite_type: str, col_name: str, table: str) -> str:
    """Map SQLite column type to PostgreSQL type."""
    t = sqlite_type.upper().strip()

    if "AUTOINCREMENT" in t or (col_name == "id" and table in SERIAL_TABLES):
        return "SERIAL"
    if "REAL" in t or "DOUBLE" in t or "FLOAT" in t:
        return "DOUBLE PRECISION"
    if "TIMESTAMPTZ" in t:
        return "TIMESTAMPTZ"
    if "TIMESTAMP" in t:
        if col_name in TIMESTAMPTZ_COLUMNS.get(table, set()):
            return "TIMESTAMPTZ"
        return "TIMESTAMP"
    if "INTEGER" in t or "INT" in t:
        return "INTEGER"
    if "BLOB" in t:
        return "BYTEA"
    # TEXT, VARCHAR, CHAR, CLOB, etc.
    return "TEXT"


def create_pg_table(pg: psycopg.Connection, table: str, columns: list[dict[str, Any]]) -> None:
    col_defs = []
    for col in columns:
        pg_type = pg_type_for(col["type"], col["name"], table)
        parts = [f'"{col["name"]}"', pg_type]
        if col["pk"] and pg_type != "SERIAL":
            parts.append("PRIMARY KEY")
        if col["notnull"] and pg_type != "SERIAL":
            parts.append("NOT NULL")
        if col["default"] is not None:
            default = col["default"]
            if default.upper() == "CURRENT_TIMESTAMP":
                parts.append("DEFAULT CURRENT_TIMESTAMP")
            elif (default.startswith("'") and default.endswith("'")) or default.replace(".", "").replace(
                "-", ""
            ).isdigit():
                parts.append(f"DEFAULT {default}")
        col_defs.append(" ".join(parts))

    ddl = f'CREATE TABLE IF NOT EXISTS "{table}" ({", ".join(col_defs)})'
    with pg.cursor() as cur:
        cur.execute(ddl)
    pg.commit()


def normalize_timestamp(val: Any) -> Any:
    """Normalize SQLite timestamp to PG-compatible format."""
    if val is None:
        return None
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=UTC)
        return val
    s = str(val).strip()
    if not s:
        return None
    # Already has timezone info
    if "+" in s or s.endswith("Z"):
        return s
    # Naive timestamp — assume UTC
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=UTC).isoformat()
    except ValueError:
        return s


def migrate_table(
    sqlite_conn: sqlite3.Connection,
    pg: psycopg.Connection,
    table: str,
    dry_run: bool = False,
) -> dict[str, int]:
    stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}

    columns = get_sqlite_columns(sqlite_conn, table)
    col_names = [c["name"] for c in columns]
    stats["total"] = get_sqlite_row_count(sqlite_conn, table)

    if dry_run:
        print(f"  [DRY RUN] {table}: {stats['total']} rows, {len(col_names)} columns")
        return stats

    # Create PG table
    create_pg_table(pg, table, columns)

    # Migrate rows
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.execute(f"SELECT * FROM [{table}]")  # noqa: S608

    tz_cols = TIMESTAMPTZ_COLUMNS.get(table, set())
    pk_cols = [c["name"] for c in columns if c["pk"]]
    has_serial = table in SERIAL_TABLES

    insert_cols = [c for c in col_names if not (has_serial and c == "id")]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_list = ", ".join(f'"{c}"' for c in insert_cols)

    # Use ON CONFLICT for idempotent re-runs
    conflict_clause = ""
    if pk_cols and not has_serial:
        conflict_target = ", ".join(f'"{c}"' for c in pk_cols)
        conflict_clause = f" ON CONFLICT ({conflict_target}) DO NOTHING"
    elif has_serial:
        conflict_clause = " ON CONFLICT DO NOTHING"

    insert_sql = f'INSERT INTO "{table}" ({col_list}) VALUES ({placeholders}){conflict_clause}'  # noqa: S608

    with pg.cursor() as pg_cur:
        for row in cur:
            try:
                values = []
                for c in insert_cols:
                    val = row[c]
                    if c in tz_cols:
                        val = normalize_timestamp(val)
                    values.append(val)
                pg_cur.execute(insert_sql, values)
                if pg_cur.rowcount > 0:
                    stats["inserted"] += 1
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                if stats["errors"] <= 3:
                    print(f"    ERROR row {row.get('id', '?')}: {e}", file=sys.stderr)

    pg.commit()

    # Reset SERIAL sequence
    if has_serial:
        with pg.cursor() as cur2:
            cur2.execute(
                f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "  # noqa: S608
                f'COALESCE((SELECT MAX(id) FROM "{table}"), 1))'
            )
        pg.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite database file")
    parser.add_argument("--pg-dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true", help="Only show stats, don't migrate")
    parser.add_argument("--tables", nargs="*", help="Specific tables to migrate (default: all)")
    args = parser.parse_args()

    print(f"SQLite: {args.sqlite_path}")
    print(f"PG:     {args.pg_dsn.split('@')[-1 if '@' in args.pg_dsn else 0]}")
    print(f"Mode:   {'DRY RUN' if args.dry_run else 'MIGRATE'}")
    print()

    # Connect SQLite
    sqlite_conn = sqlite3.connect(args.sqlite_path)
    sqlite_tables = get_sqlite_tables(sqlite_conn)
    print(f"SQLite tables ({len(sqlite_tables)}): {', '.join(sqlite_tables)}")

    # Connect PG (skip in dry-run)
    pg = None
    if not args.dry_run:
        pg = psycopg.connect(args.pg_dsn, row_factory=dict_row)
        with pg.cursor() as cur:
            cur.execute("SET TIME ZONE 'UTC'")
        pg.commit()
        print("PG connected (timezone=UTC)")
    else:
        print("PG connection skipped (dry-run)")
    print()

    # Determine tables to migrate
    if args.tables:
        tables = [t for t in TABLE_ORDER if t in args.tables]
        extra = [t for t in args.tables if t not in TABLE_ORDER]
        tables.extend(extra)
    else:
        tables = [t for t in TABLE_ORDER if t in sqlite_tables]
        extra = [t for t in sqlite_tables if t not in TABLE_ORDER]
        tables.extend(extra)

    print(f"Migrating {len(tables)} tables...\n")

    total_stats = {"total": 0, "inserted": 0, "skipped": 0, "errors": 0}
    for table in tables:
        if table not in sqlite_tables:
            print(f"  SKIP {table}: not in SQLite")
            continue
        if table == "sqlite_sequence":
            continue
        stats = migrate_table(sqlite_conn, pg, table, dry_run=args.dry_run)
        status = "OK" if stats["errors"] == 0 else f"ERRORS={stats['errors']}"
        print(f"  {table}: total={stats['total']} inserted={stats['inserted']} skipped={stats['skipped']} [{status}]")
        for k in total_stats:
            total_stats[k] += stats[k]

    print(
        f"\nTotal: {total_stats['total']} rows, "
        f"inserted={total_stats['inserted']}, "
        f"skipped={total_stats['skipped']}, "
        f"errors={total_stats['errors']}"
    )

    if not args.dry_run and total_stats["errors"] == 0:
        print("\nMigration complete. Run verify_postgres.py to validate.")

    sqlite_conn.close()
    if pg:
        pg.close()


if __name__ == "__main__":
    main()
