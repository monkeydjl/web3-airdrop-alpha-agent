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

    # 目标库已有数据时默认整体拒绝（防止误跑两次把数据插两遍）；
    # 确认要重灌时显式清空本次涉及的这些表再迁移：
    python scripts/migrate_sqlite_to_pg.py \
        --sqlite-path data/airdrop.db \
        --pg-dsn postgresql://... --force

迁移完成后：
    python scripts/verify_postgres.py  # 冒烟验证
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import zlib
from datetime import UTC, datetime
from typing import Any

try:
    import psycopg
    from psycopg import sql
    from psycopg.rows import DictRow, dict_row
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
    return int(conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0])  # noqa: S608


def detect_auto_column(conn: sqlite3.Connection, table: str, columns: list[dict[str, Any]]) -> str | None:
    """识别 SQLite 中真正的自增列（迁移到 PG 后应为 SERIAL）。

    SQLite 的 `PRAGMA table_info` 只返回声明类型（`INTEGER`），不会暴露
    `AUTOINCREMENT` 关键字，所以不能靠类型字符串判断。可靠判据是 rowid
    别名：单列 INTEGER 主键、且表不是 WITHOUT ROWID。这类列即使没写
    AUTOINCREMENT，插入时省略也会自动分配；而 `sqlite_sequence` 只在显式
    AUTOINCREMENT 且已插过数据后才有记录，空表查不到，故以 rowid 为准。
    """
    pk_cols = [c for c in columns if c["pk"]]
    if len(pk_cols) != 1:
        return None  # 复合主键没有自增列
    col = pk_cols[0]
    if "INT" not in col["type"].upper():
        return None
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if ddl and ddl[0] and "WITHOUT ROWID" in ddl[0].upper():
        return None
    # sqlite_sequence 只在表已插入数据后才有记录，空表无法据此判定，
    # 因此这里只用 rowid 别名，两者对非空表结论一致。
    return str(col["name"])


def get_sqlite_unique_indexes(conn: sqlite3.Connection, table: str) -> list[list[str]]:
    """返回 SQLite 侧 UNIQUE 索引/约束的列组合（含单列与复合）。

    `PRAGMA index_list` 的 origin：'pk' 是主键（已由 PRIMARY KEY 覆盖）、
    'u' 是 UNIQUE 约束、'c' 是 CREATE INDEX。部分索引与表达式索引无法映射
    成普通 PG 唯一索引，直接跳过。
    """
    result: list[list[str]] = []
    for row in conn.execute(f"PRAGMA index_list([{table}])").fetchall():
        index_name = str(row[1])
        is_unique = bool(row[2])
        origin = str(row[3]) if len(row) > 3 else "c"
        partial = bool(row[4]) if len(row) > 4 else False
        if not is_unique or origin == "pk" or partial:
            continue
        info = conn.execute(f"PRAGMA index_info([{index_name}])").fetchall()
        cols = [r[2] for r in sorted(info, key=lambda r: r[0])]
        if not cols or any(c is None for c in cols):
            continue
        result.append([str(c) for c in cols])
    return result


def pg_index_name(table: str, columns: list[str]) -> str:
    """可预测的唯一索引名：uq_<表>_<列...>，超过 PG 63 字节上限时截断加 CRC。"""
    base = "uq_" + "_".join([table, *columns])
    if len(base.encode()) <= 63:
        return base
    digest = f"{zlib.crc32(base.encode()):08x}"
    return f"{base.encode()[:54].decode(errors='ignore')}_{digest}"


def get_pg_unique_indexes(pg: psycopg.Connection[DictRow], table: str) -> set[frozenset[Any]]:
    """列出 PG 目标表上已有的普通唯一索引（忽略部分索引/表达式索引）。"""
    rows = pg.execute(
        """
        SELECT array_agg(a.attname ORDER BY k.ord) AS cols
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN unnest(i.indkey) WITH ORDINALITY AS k(attnum, ord) ON true
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname = 'public' AND t.relname = %s
          AND i.indisunique AND i.indpred IS NULL AND i.indexprs IS NULL
          AND a.attnum > 0 AND NOT a.attisdropped
        GROUP BY i.indexrelid
        """,
        (table,),
    ).fetchall()
    return {frozenset(r["cols"]) for r in rows}


def create_pg_unique_indexes(
    pg: psycopg.Connection[DictRow],
    table: str,
    sqlite_conn: sqlite3.Connection,
) -> None:
    """把 SQLite 的 UNIQUE 索引复制到 PG（幂等）。

    迁入 alembic 已建表的库时，等价唯一索引通常已存在（只是名字不同），
    因此按列集合比对后跳过，不重复建索引、不改动既有 schema。
    """
    existing = get_pg_unique_indexes(pg, table)
    for cols in get_sqlite_unique_indexes(sqlite_conn, table):
        key = frozenset(cols)
        if key in existing:
            continue
        stmt = sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {tbl} ({cols})").format(
            name=sql.Identifier(pg_index_name(table, cols)),
            tbl=sql.Identifier(table),
            cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
        )
        with pg.cursor() as cur:
            cur.execute(stmt)
        existing.add(key)
    pg.commit()


def pg_type_for(sqlite_type: str, col_name: str, table: str) -> str:
    """Map SQLite column type to PostgreSQL type."""
    t = sqlite_type.upper().strip()
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


def create_pg_table(
    pg: psycopg.Connection[DictRow],
    table: str,
    columns: list[dict[str, Any]],
    auto_column: str | None = None,
) -> None:
    col_defs = []
    for col in columns:
        pg_type = "SERIAL" if col["name"] == auto_column else pg_type_for(col["type"], col["name"], table)
        parts = [f'"{col["name"]}"', pg_type]
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

    # 复合主键必须聚合成一条约束，逐列写 PRIMARY KEY 会被 PG 拒绝
    # （notification_reads 就是这种表）。pk 字段是 SQLite 中主键的序号，
    # 按它排序才能保持与 SQLite 一致的主键列顺序。
    pk_cols = sorted((c for c in columns if c["pk"]), key=lambda c: c["pk"])
    if pk_cols:
        pk_list = ", ".join(f'"{c["name"]}"' for c in pk_cols)
        col_defs.append(f"PRIMARY KEY ({pk_list})")

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
    pg: psycopg.Connection[DictRow] | None,
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

    assert pg is not None, "migrate_table 在非 dry-run 下需要 PG 连接"

    # Create PG table (IF NOT EXISTS：已由 alembic 建表的库保持原 schema 不动)
    auto_column = detect_auto_column(sqlite_conn, table, columns)
    create_pg_table(pg, table, columns, auto_column=auto_column)
    # 复制 SQLite 的 UNIQUE 索引；等价索引已存在时跳过
    create_pg_unique_indexes(pg, table, sqlite_conn)

    # Migrate rows
    sqlite_conn.row_factory = sqlite3.Row
    cur = sqlite_conn.execute(f"SELECT * FROM [{table}]")  # noqa: S608

    tz_cols = TIMESTAMPTZ_COLUMNS.get(table, set())
    pk_cols = [c["name"] for c in columns if c["pk"]]
    has_serial = auto_column is not None

    insert_cols = [c for c in col_names if c != auto_column]
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
                    pk_desc = row.keys()
                    row_id = row["id"] if "id" in pk_desc else "?"
                    print(f"    ERROR row {row_id}: {e}", file=sys.stderr)

    pg.commit()

    # Reset SERIAL sequence（仅当目标列确实有序列；迁入 alembic 既有表时
    # pg_get_serial_sequence 可能为 NULL，此时跳过，避免 setval(NULL) 报错）
    if has_serial:
        assert auto_column is not None
        with pg.cursor() as cur2:
            cur2.execute("SELECT pg_get_serial_sequence(%s, %s) AS seq", (table, auto_column))
            seq_row = cur2.fetchone()
            seq_name = seq_row["seq"] if seq_row else None
            if seq_name:
                # is_called=false：下一次 nextval 直接返回 max+1；空表返回 1，
                # 不跳号（原来的 setval(...,1) 会让空表首值为 2）。
                setval_sql = sql.SQL(
                    "SELECT setval(%s::regclass, COALESCE((SELECT MAX({col}) FROM {tbl}), 0) + 1, false)"
                ).format(col=sql.Identifier(auto_column), tbl=sql.Identifier(table))
                cur2.execute(setval_sql, (seq_name,))
        pg.commit()

    return stats


def table_exists(pg: psycopg.Connection[DictRow], table: str) -> bool:
    row = pg.execute(
        "SELECT 1 AS ok FROM information_schema.tables WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchone()
    return row is not None


def find_non_empty_targets(pg: psycopg.Connection[DictRow], tables: list[str]) -> list[tuple[str, int]]:
    """返回目标库中已有数据的表及其行数（用于防止重复灌库）。"""
    non_empty: list[tuple[str, int]] = []
    for table in tables:
        if table == "sqlite_sequence" or not table_exists(pg, table):
            continue
        count_sql = sql.SQL("SELECT COUNT(*) AS c FROM {tbl}").format(tbl=sql.Identifier(table))
        row = pg.execute(count_sql).fetchone()
        count = int(row["c"]) if row else 0
        if count > 0:
            non_empty.append((table, count))
    return non_empty


def clear_tables(pg: psycopg.Connection[DictRow], tables: list[str]) -> None:
    """--force 的显式逃生口：清空目标表后完整重灌（用 DELETE，避免 TRUNCATE 的 FK 连带）。"""
    for table in tables:
        pg.execute(sql.SQL("DELETE FROM {tbl}").format(tbl=sql.Identifier(table)))
    pg.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate SQLite to PostgreSQL")
    parser.add_argument("--sqlite-path", required=True, help="Path to SQLite database file")
    parser.add_argument("--pg-dsn", required=True, help="PostgreSQL DSN")
    parser.add_argument("--dry-run", action="store_true", help="Only show stats, don't migrate")
    parser.add_argument(
        "--force",
        action="store_true",
        help="清空目标库中本次涉及的非空表后重灌（默认遇到非空表直接拒绝）",
    )
    parser.add_argument("--tables", nargs="*", help="Specific tables to migrate (default: all)")
    args = parser.parse_args()

    print(f"SQLite: {args.sqlite_path}")
    print(f"PG:     {args.pg_dsn.split('@')[-1 if '@' in args.pg_dsn else 0]}")
    print(f"Mode:   {'DRY RUN' if args.dry_run else 'MIGRATE'}{' (FORCE)' if args.force else ''}")
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

    # 非空目标库防重：SERIAL 表的 id 由 PG 重新分配，ON CONFLICT 无法识别
    # 上一轮插入的行，继续执行必然重复。默认在写入任何数据前整体拒绝，
    # --force 才显式清空重灌（一次性迁移 + 误跑两次的最安全默认）。
    if not args.dry_run:
        assert pg is not None
        non_empty = find_non_empty_targets(pg, tables)
        if non_empty and not args.force:
            detail = ", ".join(f"{t}({n})" for t, n in non_empty)
            print(
                f"ABORT: target tables already contain rows: {detail}\n"
                "Re-running would insert the same rows again (SERIAL ids are reassigned).\n"
                "Use --force to clear these tables and reload from SQLite.",
                file=sys.stderr,
            )
            sqlite_conn.close()
            pg.close()
            sys.exit(2)
        if non_empty:
            clear_tables(pg, [t for t, _ in non_empty])
            print(f"  [FORCE] cleared {len(non_empty)} non-empty target tables")
            print()

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
