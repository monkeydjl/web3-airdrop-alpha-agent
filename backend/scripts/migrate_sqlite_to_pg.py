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
import re
import sqlite3
import sys
import zlib
from dataclasses import dataclass
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


class IndexSqlError(Exception):
    """SQLite 索引 DDL 中存在无法安全等价翻译到 PG 的构造。"""


@dataclass
class UniqueIndexSpec:
    source_name: str
    pg_name: str
    pg_terms: list[str]
    pg_where: str | None
    kind: str  # columns | partial | expression | skipped
    columns: list[str] | None = None
    skip_reason: str | None = None


_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\.\d+")
_ALLOWED_FUNCS = {
    "lower",
    "upper",
    "trim",
    "ltrim",
    "rtrim",
    "coalesce",
    "ifnull",
    "nullif",
    "length",
    "replace",
}
_FUNC_RENAMES = {"ifnull": "coalesce"}


def _quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _crc(text: str) -> str:
    return f"{zlib.crc32(text.encode()):08x}"


def _tokenize(sql: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    i = 0
    while i < len(sql):
        ch = sql[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "'":
            j = i + 1
            buf = ["'"]
            while j < len(sql):
                if sql[j] == "'":
                    if j + 1 < len(sql) and sql[j + 1] == "'":
                        buf.append("''")
                        j += 2
                        continue
                    buf.append("'")
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            else:
                raise IndexSqlError("unterminated string literal")
            tokens.append(("string", "".join(buf)))
            i = j
            continue
        if ch in '"`[':
            close = "]" if ch == "[" else ch
            j = i + 1
            buf = []
            while j < len(sql):
                if sql[j] == close:
                    if close == '"' and j + 1 < len(sql) and sql[j + 1] == '"':
                        buf.append('"')
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            else:
                raise IndexSqlError("unterminated quoted identifier")
            tokens.append(("ident", "".join(buf)))
            i = j
            continue
        match = _NUMBER_RE.match(sql, i)
        if match:
            tokens.append(("number", match.group(0)))
            i = match.end()
            continue
        match = _IDENT_RE.match(sql, i)
        if match:
            tokens.append(("ident", match.group(0)))
            i = match.end()
            continue
        two = sql[i : i + 2]
        if two in ("<=", ">=", "<>", "!=", "||"):
            tokens.append(("op", two))
            i += 2
            continue
        if ch in "=<>+-*/%(),.":
            tokens.append((ch if ch in "(),." else "op", ch))
            i += 1
            continue
        raise IndexSqlError(f"unsupported character {ch!r}")
    return tokens


class _IndexSqlParser:
    """把 SQLite 索引项/WHERE 条件转换成 PG 等价片段。

    只接受可证明等价的构造：列引用、字面量、括号、拼接、算术、白名单函数，
    以及 AND/OR/NOT/IS [NOT] NULL/比较/IN 列表。LIKE、GLOB、BETWEEN、COLLATE、
    子查询和 SQLite 特有函数一律抛 IndexSqlError，由调用方记录为跳过。
    """

    def __init__(self, tokens: list[tuple[str, str]], columns: dict[str, str]) -> None:
        self._tokens = tokens
        self._pos = 0
        self._columns = columns

    def _peek(self) -> tuple[str, str]:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else ("eof", "")

    def _take(self) -> tuple[str, str]:
        tok = self._peek()
        if tok[0] == "eof":
            raise IndexSqlError("unexpected end of index definition")
        self._pos += 1
        return tok

    def _accept(self, kind: str, value: str | None = None) -> bool:
        tok = self._peek()
        if tok[0] == kind and (value is None or tok[1].lower() == value):
            self._pos += 1
            return True
        return False

    def _expect(self, kind: str, value: str | None = None) -> None:
        if not self._accept(kind, value):
            raise IndexSqlError(f"expected {value or kind}, got {self._peek()[1]!r}")

    def _is_keyword(self, word: str) -> bool:
        tok = self._peek()
        return tok[0] == "ident" and tok[1].lower() == word

    def statement(self) -> str:
        result = self._concat()
        if self._peek()[0] != "eof":
            raise IndexSqlError(f"unexpected token {self._peek()[1]!r}")
        return result

    def condition(self) -> str:
        result = self._or()
        if self._peek()[0] != "eof":
            raise IndexSqlError(f"unsupported predicate near {self._peek()[1]!r}")
        return result

    def _concat(self) -> str:
        left = self._additive()
        while self._accept("op", "||"):
            left = f"({left} || {self._additive()})"
        return left

    def _additive(self) -> str:
        left = self._term()
        while True:
            tok = self._peek()
            if tok[0] != "op" or tok[1] not in ("+", "-"):
                return left
            self._take()
            left = f"({left} {tok[1]} {self._term()})"

    def _term(self) -> str:
        left = self._unary()
        while True:
            tok = self._peek()
            if tok[0] != "op" or tok[1] not in ("*", "/", "%"):
                return left
            self._take()
            left = f"({left} {tok[1]} {self._unary()})"

    def _unary(self) -> str:
        if self._accept("op", "-"):
            return f"(-{self._unary()})"
        return self._primary()

    def _primary(self) -> str:
        tok = self._peek()
        if tok[0] == "number":
            self._take()
            return tok[1]
        if tok[0] == "string":
            self._take()
            return tok[1]
        if tok[0] == "ident":
            self._take()
            if self._peek()[0] == "(":
                return self._function(tok[1])
            if tok[1].lower() == "null":
                return "NULL"
            canonical = self._columns.get(tok[1].lower())
            if canonical is None:
                raise IndexSqlError(f"unknown or unsupported identifier {tok[1]}")
            return _quote_ident(canonical)
        if tok[0] == "(":
            self._take()
            inner = self._concat()
            self._expect(")")
            return f"({inner})"
        raise IndexSqlError(f"unsupported token {tok[1]!r}")

    def _function(self, name: str) -> str:
        fn = name.lower()
        if fn not in _ALLOWED_FUNCS:
            raise IndexSqlError(f"unsupported function {name}()")
        self._expect("(")
        args: list[str] = []
        if self._peek()[0] != ")":
            args.append(self._concat())
            while self._accept(","):
                args.append(self._concat())
        self._expect(")")
        if not args:
            raise IndexSqlError(f"{name}() has no arguments")
        return f"{_FUNC_RENAMES.get(fn, fn)}({', '.join(args)})"

    def _or(self) -> str:
        left = self._and()
        while self._is_keyword("or"):
            self._take()
            left = f"({left} OR {self._and()})"
        return left

    def _and(self) -> str:
        left = self._not()
        while self._is_keyword("and"):
            self._take()
            left = f"({left} AND {self._not()})"
        return left

    def _not(self) -> str:
        if self._is_keyword("not"):
            self._take()
            return f"(NOT {self._not()})"
        return self._predicate()

    def _predicate(self) -> str:
        if self._peek()[0] == "(":
            save = self._pos
            try:
                self._take()
                inner = self._or()
                self._expect(")")
                return f"({inner})"
            except IndexSqlError:
                self._pos = save
        left = self._concat()
        if self._is_keyword("is"):
            self._take()
            negated = self._is_keyword("not")
            if negated:
                self._take()
            if self._is_keyword("null"):
                self._take()
                return f"({left} IS {'NOT ' if negated else ''}NULL)"
            right = self._concat()
            op = "IS DISTINCT FROM" if negated else "IS NOT DISTINCT FROM"
            return f"({left} {op} {right})"
        tok = self._peek()
        if tok[0] == "op" and tok[1] in ("=", "!=", "<>", "<", "<=", ">", ">="):
            self._take()
            return f"({left} {tok[1]} {self._concat()})"
        if self._is_keyword("not") or self._is_keyword("in"):
            negated = self._is_keyword("not")
            if negated:
                self._take()
            if not self._is_keyword("in"):
                raise IndexSqlError("NOT is only supported before IN in index predicates")
            self._take()
            self._expect("(")
            items: list[str] = []
            if self._peek()[0] != ")":
                items.append(self._literal())
                while self._accept(","):
                    items.append(self._literal())
            self._expect(")")
            if not items:
                raise IndexSqlError("empty IN list")
            return f"({left} {'NOT IN' if negated else 'IN'} ({', '.join(items)}))"
        for word in ("like", "glob", "between", "collate"):
            if self._is_keyword(word):
                raise IndexSqlError(f"{word.upper()} predicate is not translated")
        raise IndexSqlError("bare expressions are not valid index predicates")

    def _literal(self) -> str:
        negated = self._accept("op", "-")
        tok = self._take()
        if tok[0] == "number":
            return ("-" if negated else "") + tok[1]
        if tok[0] == "string" and not negated:
            return tok[1]
        if tok[0] == "ident" and tok[1].lower() == "null" and not negated:
            return "NULL"
        raise IndexSqlError("IN list supports literals only")


def _split_index_ddl(ddl: str) -> tuple[list[list[tuple[str, str]]], list[tuple[str, str]] | None]:
    """拆出 CREATE INDEX 的索引项列表与可选 WHERE 子句 token。"""
    tokens = _tokenize(ddl)
    pos = 0

    def take() -> tuple[str, str]:
        nonlocal pos
        if pos >= len(tokens):
            raise IndexSqlError("unexpected end of CREATE INDEX statement")
        tok = tokens[pos]
        pos += 1
        return tok

    def word(expected: str) -> None:
        tok = take()
        if tok[0] != "ident" or tok[1].lower() != expected:
            raise IndexSqlError(f"expected {expected.upper()} in CREATE INDEX statement")

    def optional_word(expected: str) -> bool:
        nonlocal pos
        if pos < len(tokens) and tokens[pos][0] == "ident" and tokens[pos][1].lower() == expected:
            pos += 1
            return True
        return False

    word("create")
    optional_word("unique")
    word("index")
    if optional_word("if"):
        word("not")
        word("exists")
    take()  # index name
    word("on")
    take()  # table name
    if take()[0] != "(":
        raise IndexSqlError("missing column list in CREATE INDEX statement")
    groups: list[list[tuple[str, str]]] = []
    group: list[tuple[str, str]] = []
    depth = 1
    while True:
        tok = take()
        if tok[0] == "(":
            depth += 1
        elif tok[0] == ")":
            depth -= 1
            if depth == 0:
                groups.append(group)
                break
        elif tok[0] == "," and depth == 1:
            groups.append(group)
            group = []
            continue
        group.append(tok)
    where_tokens = tokens[pos:] or None
    if where_tokens:
        if where_tokens[0][0] != "ident" or where_tokens[0][1].lower() != "where":
            raise IndexSqlError("unsupported clause after index columns")
        where_tokens = where_tokens[1:] or None
    return groups, where_tokens


def _index_name(table: str, parts: list[str], where_sql: str | None) -> str:
    """可预测的唯一索引名：uq_<表>_<列/expr_crc...>[_p<crc>]。"""
    base = "uq_" + "_".join([table, *parts])
    if where_sql:
        base += "_p" + _crc(where_sql)
    if len(base.encode()) <= 63:
        return base
    return f"{base.encode()[:54].decode(errors='ignore')}_{_crc(base)}"


def collect_unique_indexes(
    conn: sqlite3.Connection,
    table: str,
    columns: list[dict[str, Any]],
) -> list[UniqueIndexSpec]:
    """收集 SQLite 的唯一索引，并翻译部分索引谓词与表达式索引。"""
    colmap = {str(c["name"]).lower(): str(c["name"]) for c in columns}
    ddl_by_name = {
        str(r[0]): str(r[1])
        for r in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?", (table,)
        ).fetchall()
        if r[1]
    }
    specs: list[UniqueIndexSpec] = []
    for row in conn.execute(f"PRAGMA index_list([{table}])").fetchall():
        source_name = str(row[1])
        is_unique = bool(row[2])
        origin = str(row[3]) if len(row) > 3 else "c"
        if not is_unique or origin == "pk":
            continue
        ddl = ddl_by_name.get(source_name)
        try:
            if ddl is None:
                # UNIQUE 表约束生成的 sqlite_autoindex：只可能是普通列
                info = conn.execute(f"PRAGMA index_info([{source_name}])").fetchall()
                names = [str(r[2]) for r in sorted(info, key=lambda r: r[0]) if r[2] is not None]
                if not names or len(names) != len(info):
                    raise IndexSqlError("autoindex has expression columns")
                specs.append(
                    UniqueIndexSpec(
                        source_name,
                        _index_name(table, names, None),
                        [_quote_ident(c) for c in names],
                        None,
                        "columns",
                        columns=names,
                    )
                )
                continue
            groups, where_tokens = _split_index_ddl(ddl)
            parts: list[str] = []
            terms: list[str] = []
            has_expression = False
            for group in groups:
                if not group:
                    raise IndexSqlError("empty index term")
                if len(group) == 1 and group[0][0] == "ident" and group[0][1].lower() in colmap:
                    canonical = colmap[group[0][1].lower()]
                    parts.append(canonical)
                    terms.append(_quote_ident(canonical))
                else:
                    expression = _IndexSqlParser([*group, ("eof", "")], colmap).statement()
                    parts.append("expr_" + _crc(expression))
                    terms.append(expression)
                    has_expression = True
            if not terms:
                raise IndexSqlError("empty index column list")
            where_sql = None
            if where_tokens:
                where_sql = _IndexSqlParser([*where_tokens, ("eof", "")], colmap).condition()
            kind = "expression" if has_expression else ("partial" if where_sql else "columns")
            specs.append(
                UniqueIndexSpec(
                    source_name,
                    _index_name(table, parts, where_sql),
                    terms,
                    where_sql,
                    kind,
                    columns=None if has_expression or where_sql else parts,
                )
            )
        except IndexSqlError as exc:
            specs.append(UniqueIndexSpec(source_name, "", [], None, "skipped", skip_reason=str(exc)))
    return specs


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


def get_pg_index_names(pg: psycopg.Connection[DictRow], table: str) -> set[str]:
    rows = pg.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = %s",
        (table,),
    ).fetchall()
    return {str(r["indexname"]) for r in rows}


def create_pg_unique_indexes(
    pg: psycopg.Connection[DictRow],
    table: str,
    sqlite_conn: sqlite3.Connection,
    columns: list[dict[str, Any]],
    report: list[tuple[str, str, str, str]],
) -> None:
    """把 SQLite 的 UNIQUE 索引复制到 PG（幂等），并记录复制/跳过清单。

    迁入 alembic 已建表的库时，等价唯一索引通常已存在（只是名字不同），
    普通列索引按列集合比对跳过；部分/表达式索引按可预测的名字判定。
    """
    existing_columns = get_pg_unique_indexes(pg, table)
    existing_names = get_pg_index_names(pg, table)
    for spec in collect_unique_indexes(sqlite_conn, table, columns):
        if spec.skip_reason:
            report.append((table, spec.source_name, "skipped", spec.skip_reason))
            continue
        if spec.columns is not None:
            key = frozenset(spec.columns)
            if key in existing_columns:
                continue
        elif spec.pg_name in existing_names:
            report.append((table, spec.source_name, "exists", "equivalent index already exists"))
            continue
        stmt = sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {tbl} ({terms}){where}").format(
            name=sql.Identifier(spec.pg_name),
            tbl=sql.Identifier(table),
            terms=sql.SQL(", ").join(sql.SQL(term) for term in spec.pg_terms),
            where=sql.SQL(" WHERE " + spec.pg_where) if spec.pg_where else sql.SQL(""),
        )
        try:
            with pg.cursor() as cur:
                cur.execute(stmt)
        except Exception as exc:
            pg.rollback()
            report.append((table, spec.source_name, "skipped", f"create failed: {exc}"))
            continue
        if spec.columns is not None:
            existing_columns.add(frozenset(spec.columns))
        existing_names.add(spec.pg_name)
        report.append((table, spec.source_name, "copied", spec.kind))
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
    index_report: list[tuple[str, str, str, str]] | None = None,
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
    # 复制 SQLite 的 UNIQUE 索引（含部分/表达式索引）；跳过项会记录原因
    create_pg_unique_indexes(pg, table, sqlite_conn, columns, index_report if index_report is not None else [])

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
    index_report: list[tuple[str, str, str, str]] = []
    for table in tables:
        if table not in sqlite_tables:
            print(f"  SKIP {table}: not in SQLite")
            continue
        if table == "sqlite_sequence":
            continue
        stats = migrate_table(sqlite_conn, pg, table, dry_run=args.dry_run, index_report=index_report)
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

    if index_report:
        copied = [r for r in index_report if r[2] == "copied"]
        exists = [r for r in index_report if r[2] == "exists"]
        skipped = [r for r in index_report if r[2] == "skipped"]
        print(f"\nUnique index replication: copied={len(copied)} exists={len(exists)} skipped={len(skipped)}")
        for table, source, _status, detail in copied:
            print(f"  copied  {table}.{source} ({detail})")
        for table, source, _status, detail in exists:
            print(f"  exists  {table}.{source}: {detail}")
        for table, source, _status, detail in skipped:
            print(f"  SKIPPED {table}.{source}: {detail}")

    if not args.dry_run and total_stats["errors"] == 0:
        print("\nMigration complete. Run verify_postgres.py to validate.")

    sqlite_conn.close()
    if pg:
        pg.close()


if __name__ == "__main__":
    main()
