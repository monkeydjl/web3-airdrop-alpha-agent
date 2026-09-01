"""Database Access Layer.

MVP: SQLite (WAL)
Optional test/V2: PostgreSQL when DATABASE_URL is set.

Reference:
- CONVENTIONS.md §13
- docs/adr/ADR-004-sqlite-to-postgres.md
- docker-compose.postgres.yml
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.config import settings

sqlite3.register_adapter(datetime, lambda value: value.isoformat(sep=" "))
sqlite3.register_adapter(date, lambda value: value.isoformat())

# Stable signed 64-bit key shared by every process serializing PostgreSQL init_db DDL.
POSTGRES_INIT_ADVISORY_LOCK_ID = 7_314_738_183_274_209_024

# ── backend detection ───────────────────────────


def is_postgres() -> bool:
    """True when DATABASE_URL points at PostgreSQL or DB_BACKEND=postgres."""
    if getattr(settings, "db_backend", "") == "postgres":
        return True
    url = (settings.database_url or "").strip()
    return url.startswith("postgresql://") or url.startswith("postgres://")


def backend_name() -> str:
    return "postgres" if is_postgres() else "sqlite"


# ── connection wrapper (minimal dual backend) ───


class DbConnection:
    """Thin wrapper so callers can use SQLite-style `?` placeholders on both backends."""

    def __init__(self, raw: Any, *, kind: str) -> None:
        self._raw = raw
        self.kind = kind  # "sqlite" | "postgres"

    def execute(self, sql: str, params: Iterable[Any] | None = None) -> Any:
        sql_n, params_n = self._normalize(sql, params)
        if self.kind == "postgres":
            cur = self._raw.cursor()
            cur.execute(sql_n, params_n or ())
            return cur
        if params_n is None:
            return self._raw.execute(sql_n)
        return self._raw.execute(sql_n, params_n)

    def executemany(self, sql: str, seq_of_params: Iterable[Iterable[Any]]) -> Any:
        sql_n, _ = self._normalize(sql, ())
        params_n = [self._normalize_params(params) for params in seq_of_params]
        if self.kind == "postgres":
            cur = self._raw.cursor()
            cur.executemany(sql_n, params_n)
            return cur
        return self._raw.executemany(sql_n, params_n)

    def executescript(self, script: str) -> None:
        if self.kind == "sqlite":
            self._raw.executescript(script)
            return
        # PG: run statements one-by-one (no SQLite executescript)。
        # 复用单个游标并在结束时关闭，避免每条 DDL 泄漏一个游标（init_db 约 90 条）。
        cur = self._raw.cursor()
        try:
            for stmt in _split_sql_statements(script):
                if stmt.strip():
                    cur.execute(stmt)
        finally:
            cur.close()

    def begin_serialized_write(self) -> None:
        """Start a write transaction before any state used for validation is read."""
        if self.kind == "sqlite":
            self._raw.execute("BEGIN IMMEDIATE")

    def begin_immediate(self) -> None:
        """Backward-compatible SQLite transaction helper."""
        self.begin_serialized_write()

    def commit(self) -> None:
        self._raw.commit()

    def rollback(self) -> None:
        self._raw.rollback()

    def close(self) -> None:
        self._raw.close()

    def __enter__(self) -> DbConnection:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _normalize(self, sql: str, params: Iterable[Any] | None) -> tuple[str, tuple[Any, ...] | None]:
        if self.kind == "postgres":
            # datetime('now', ?)  must become interval cast before `?` rewrite
            # SQLite datetime('now') 语义为 UTC。Postgres NOW() 返回带时区的
            # timestamptz，写入 naive TIMESTAMP 列时按会话时区截断，非 UTC 服务器
            # 会产生偏移。统一改写为 UTC 墙钟以对齐两端行为。
            sql = re.sub(
                r"datetime\s*\(\s*'now'\s*,\s*\?\s*\)",
                "((NOW() AT TIME ZONE 'UTC') + (%s)::interval)",
                sql,
                flags=re.IGNORECASE,
            )
            sql = re.sub(
                r"datetime\s*\(\s*'now'\s*,\s*'([^']+)'\s*\)",
                r"((NOW() AT TIME ZONE 'UTC') + INTERVAL '\1')",
                sql,
                flags=re.IGNORECASE,
            )
            sql = re.sub(
                r"datetime\s*\(\s*'now'\s*\)",
                "(NOW() AT TIME ZONE 'UTC')",
                sql,
                flags=re.IGNORECASE,
            )
            # remaining SQLite placeholders
            sql = sql.replace("?", "%s")
        if params is None:
            return sql, None
        return sql, self._normalize_params(params)

    def _normalize_params(self, params: Iterable[Any]) -> tuple[Any, ...]:
        if self.kind == "postgres":
            return tuple(params)
        return tuple(
            value.isoformat(sep=" ")
            if isinstance(value, datetime)
            else value.isoformat()
            if isinstance(value, date)
            else value
            for value in params
        )


# 已确认存在的 SQLite 数据目录，避免每次建连重复 mkdir
_ENSURED_SQLITE_DIRS: set[str] = set()


def get_connection() -> DbConnection:
    """Return a DB connection (SQLite by default; PostgreSQL if DATABASE_URL set)."""
    if is_postgres():
        return _connect_postgres()
    return _connect_sqlite()


def _connect_sqlite() -> DbConnection:
    db_path = Path(settings.db_path)
    parent = db_path.parent
    # mkdir 是 syscall，每次建连都做在热路径上是浪费；目录只需确认一次
    if str(parent) not in _ENSURED_SQLITE_DIRS:
        parent.mkdir(parents=True, exist_ok=True)
        _ENSURED_SQLITE_DIRS.add(str(parent))
    # 路由处理器现由线程池并发执行，SQLite 写锁竞争是真实存在的；
    # 显式 busy_timeout 让并发写等待而不是直接抛 "database is locked"。
    conn = sqlite3.connect(str(db_path), timeout=settings.sqlite_busy_timeout_seconds)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(f"PRAGMA busy_timeout={int(settings.sqlite_busy_timeout_seconds * 1000)}")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return DbConnection(conn, kind="sqlite")


def _connect_postgres() -> DbConnection:
    import psycopg
    from psycopg.rows import dict_row

    dsn = _to_psycopg_dsn(settings.database_url or "")
    conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=False)
    return DbConnection(conn, kind="postgres")


def _to_psycopg_dsn(url: str) -> str:
    """Accept postgresql:// or postgres:// URLs for psycopg3."""
    # strip SQLAlchemy-style +driver suffixes
    url = url.replace("postgresql+asyncpg://", "postgresql://")
    url = url.replace("postgresql+psycopg://", "postgresql://")
    url = url.replace("postgresql+psycopg2://", "postgresql://")
    return url


def _split_sql_statements(script: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts


def _column_exists(conn: DbConnection, table: str, column: str) -> bool:
    if conn.kind == "sqlite":
        cursor = conn.execute(f"PRAGMA table_info({table})")
        return any(row["name"] == column for row in cursor.fetchall())
    cursor = conn.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
        """,
        (table, column),
    )
    return cursor.fetchone() is not None


def _add_column_if_not_exists(
    conn: DbConnection,
    table: str,
    column: str,
    definition: str,
) -> None:
    if not _column_exists(conn, table, column):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _sqlite_ddl() -> str:
    return """
            CREATE TABLE IF NOT EXISTS projects (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                url             TEXT,
                sector          TEXT,
                stage           TEXT,
                score           INTEGER,
                label           TEXT,
                recommendation  TEXT,
                confidence      REAL,
                weight_version  TEXT,
                veto            TEXT,
                reason          TEXT,
                narrative_json  TEXT,
                team_json       TEXT,
                risk_json       TEXT,
                tokenomics_json TEXT,
                raw_signals     TEXT,
                sub_scores      TEXT,
                meta            TEXT,
                source          TEXT,
                raw_signals_hash TEXT,
                fetched_at      TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                project_id  TEXT,
                agent_name  TEXT,
                input       TEXT,
                output      TEXT,
                error       TEXT,
                duration_ms INTEGER,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS data_sources (
                source_id       TEXT PRIMARY KEY,
                source_type     TEXT NOT NULL,
                source_name     TEXT NOT NULL,
                enabled         INTEGER DEFAULT 1,
                last_sync       TIMESTAMP,
                sync_status     TEXT DEFAULT 'idle',
                api_calls_today INTEGER DEFAULT 0,
                api_limit       INTEGER,
                config          TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS raw_projects (
                raw_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                dedup_key       TEXT NOT NULL,
                raw_data        TEXT NOT NULL,
                discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed       INTEGER DEFAULT 0,
                processed_at    TIMESTAMP,
                project_id      TEXT,
                discovery_score REAL DEFAULT 0.0,
                quarantined     INTEGER DEFAULT 0,
                quarantine_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS project_signals (
                signal_id       TEXT PRIMARY KEY,
                project_id      TEXT,
                dedup_key       TEXT,
                signal_type     TEXT NOT NULL,
                signal_source   TEXT NOT NULL,
                signal_data     TEXT NOT NULL,
                signal_strength REAL DEFAULT 0.0,
                captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS collection_logs (
                log_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                started_at      TIMESTAMP NOT NULL,
                finished_at     TIMESTAMP,
                items_collected INTEGER DEFAULT 0,
                items_new       INTEGER DEFAULT 0,
                items_duplicate INTEGER DEFAULT 0,
                status          TEXT,
                error_message   TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_projects_archive (
                raw_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                dedup_key       TEXT NOT NULL,
                raw_data        TEXT NOT NULL,
                discovered_at   TIMESTAMP,
                processed       INTEGER DEFAULT 0,
                processed_at    TIMESTAMP,
                project_id      TEXT,
                discovery_score REAL DEFAULT 0.0,
                archived_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS project_signals_archive (
                signal_id       TEXT PRIMARY KEY,
                project_id      TEXT,
                dedup_key       TEXT,
                signal_type     TEXT NOT NULL,
                signal_source   TEXT NOT NULL,
                signal_data     TEXT NOT NULL,
                signal_strength REAL DEFAULT 0.0,
                captured_at     TIMESTAMP,
                archived_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT NOT NULL,
                user_id     TEXT,
                signal      TEXT NOT NULL,
                note        TEXT,
                outcome     TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT,
                user_id     TEXT,
                event_type  TEXT NOT NULL,
                detail      TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 用户交互/参与记录（用于后期校准与复盘）
            CREATE TABLE IF NOT EXISTS interactions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      TEXT NOT NULL,
                user_id         TEXT,
                status          TEXT NOT NULL DEFAULT 'planned',
                started_at      TEXT,
                ended_at        TEXT,
                cost_usd        REAL,
                profit_usd      REAL,
                hours_spent     REAL,
                activities      TEXT,
                note            TEXT,
                outcome         TEXT,
                score_at_start  INTEGER,
                label_at_start  TEXT,
                wallet_cohort_id TEXT,
                wallet_count INTEGER DEFAULT 1,
                actual_hard_cost_usd REAL,
                actual_time_minutes INTEGER,
                eligibility_result TEXT,
                survival_result TEXT,
                disqualification_reason TEXT,
                reward_received_usd REAL,
                claim_cost_usd REAL,
                opportunity_assessment_id TEXT,
                opportunity_model_version TEXT,
                opportunity_profile_version TEXT,
                outcome_observed_at TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_evidence (
                evidence_id         TEXT PRIMARY KEY,
                project_id          TEXT NOT NULL,
                factor_key          TEXT NOT NULL,
                value_json          TEXT NOT NULL,
                value_type          TEXT NOT NULL,
                observation_type    TEXT NOT NULL,
                source_url          TEXT NOT NULL,
                source_type         TEXT NOT NULL,
                source_grade        TEXT NOT NULL,
                observed_at         TIMESTAMP NOT NULL,
                effective_at        TIMESTAMP,
                expires_at          TIMESTAMP,
                verification_status TEXT NOT NULL,
                independence_group  TEXT NOT NULL,
                raw_snapshot_ref    TEXT,
                supersedes_evidence_id TEXT,
                created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_assessments (
                assessment_id      TEXT PRIMARY KEY,
                project_id         TEXT NOT NULL,
                model_version      TEXT NOT NULL,
                profile_version    TEXT NOT NULL,
                assessment_json    TEXT NOT NULL,
                decision_status    TEXT NOT NULL,
                public_label       TEXT NOT NULL,
                decision_value     REAL,
                overall_confidence REAL NOT NULL,
                scored_at          TIMESTAMP NOT NULL,
                review_at          TIMESTAMP,
                expires_at         TIMESTAMP NOT NULL,
                created_at         TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots (
                snapshot_id        TEXT PRIMARY KEY,
                schema_version     TEXT NOT NULL,
                run_id             TEXT NOT NULL,
                source_id          TEXT NOT NULL,
                dedup_key          TEXT NOT NULL CHECK(length(trim(dedup_key))>0),
                provider_entity_id TEXT NOT NULL,
                payload_sha256     TEXT NOT NULL,
                payload_json       TEXT NOT NULL,
                source_url         TEXT NOT NULL,
                collected_at       TIMESTAMP NOT NULL
            );

            -- 用户 Watchlist（ADR-008 V2）
            CREATE TABLE IF NOT EXISTS watchlist (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id  TEXT NOT NULL,
                user_id     TEXT,
                note        TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, user_id)
            );

            -- 通知已读状态（按用户 + 稳定 notification_id）
            CREATE TABLE IF NOT EXISTS notification_reads (
                user_id          TEXT NOT NULL,
                notification_id  TEXT NOT NULL,
                read_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, notification_id)
            );
            CREATE INDEX IF NOT EXISTS idx_notification_reads_user
                ON notification_reads(user_id);

            -- 决策推派出站日志（ACTION_LOOP_DESIGN.md §2.5）
            -- (event_key, channel) 唯一：同事件同通道天然去重，重发靠 UPSERT 忽略。
            CREATE TABLE IF NOT EXISTS notify_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type  TEXT NOT NULL,
                event_key   TEXT NOT NULL,
                channel     TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_error  TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sent_at     TIMESTAMP,
                UNIQUE (event_key, channel)
            );
            CREATE INDEX IF NOT EXISTS idx_notify_log_status
                ON notify_log(status, created_at);

            -- 参与流水（ACTION_LOOP_DESIGN.md §3，F2）
            -- plan/task 两级：plan 是「我在参与这个项目」，task 是具体动作。
            -- user_id 来自 token 身份（get_current_user），不接受请求体自报。
            -- 刻意不设 SQL 级外键（全仓约定，见 opportunity 的同类测试）：
            -- 级联删除由路由层显式先删 task 再删 plan 保证。
            --
            CREATE TABLE IF NOT EXISTS participation_plans (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                note        TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMP,
                UNIQUE (user_id, project_id)
            );

            CREATE TABLE IF NOT EXISTS participation_tasks (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                plan_id      INTEGER NOT NULL,
                ref          TEXT,
                title        TEXT NOT NULL,
                kind         TEXT NOT NULL DEFAULT 'other',
                status       TEXT NOT NULL DEFAULT 'todo',
                url          TEXT,
                due_at       TIMESTAMP,
                note         TEXT,
                completed_at TIMESTAMP,
                created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_participation_tasks_plan
                ON participation_tasks(plan_id, status);

            -- 收益台账（ACTION_LOOP_DESIGN.md §4，F3）
            -- entries = 投入，outcomes = 产出，按 (user_id, project_id) 聚合出 ROI。
            -- 诚实边界：amount_usd 以人工录入为准，MVP 不做链上自动取价；
            -- tx_hash 只是凭证存档，不自动验证。
            -- source 区分 live（真实操作留痕）与 backtest（历史回测导出），
            -- 校准时两类样本分开统计（§4.3），不混算。
            --
            CREATE TABLE IF NOT EXISTS roi_entries (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                kind        TEXT NOT NULL,
                amount_usd  REAL,
                hours       REAL,
                note        TEXT,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_roi_entries_user_project
                ON roi_entries(user_id, project_id);

            CREATE TABLE IF NOT EXISTS roi_outcomes (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                event       TEXT NOT NULL,
                amount_usd  REAL,
                tokens      REAL,
                tx_hash     TEXT,
                source      TEXT NOT NULL DEFAULT 'manual',
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_roi_outcomes_user_project
                ON roi_outcomes(user_id, project_id);

            -- 权重校准变更日志（WEIGHT_CALIBRATION.md §7）
            CREATE TABLE IF NOT EXISTS weight_changelog (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                from_version    TEXT,
                to_version      TEXT,
                weights_json    TEXT NOT NULL,
                sample_size     INTEGER,
                metrics_json    TEXT,
                triggered_by    TEXT,
                status          TEXT DEFAULT 'candidate',
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- ── V2 新表（§5.4） ──────────────────────
            CREATE TABLE IF NOT EXISTS quarantine (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      TEXT,
                raw_data        TEXT NOT NULL,
                failure_reason  TEXT NOT NULL,
                severity        TEXT DEFAULT 'warning',
                status          TEXT DEFAULT 'pending',
                resolved_at     TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS project_history (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id      TEXT NOT NULL,
                run_id          TEXT NOT NULL,
                score           INTEGER,
                label           TEXT,
                stage           TEXT,
                weight_version  TEXT,
                snapshot        TEXT NOT NULL,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                action      TEXT NOT NULL,
                "user"      TEXT NOT NULL,
                detail      TEXT,
                ip          TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS llm_eval_changelog (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                eval_date       TIMESTAMP NOT NULL,
                sample_count    INTEGER NOT NULL,
                rule_accuracy   REAL NOT NULL,
                llm_accuracy    REAL NOT NULL,
                llm_cost_usd    REAL NOT NULL,
                decision        TEXT NOT NULL,
                detail          TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                detail      TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- LLM 日花费账本（迁移 0004）。
            -- LLM_DAILY_BUDGET_USD 此前是装饰性配置：能填、能查、不拦截，
            -- 因为全仓没有任何地方在累计花费 —— 没有累计就无从超限。
            --
            -- 为什么必须落库而不是内存计数：内存计数在进程重启时归零，而
            -- "花超了"恰好是最可能伴随重启的场景；多 worker / 滚动更新时
            -- 每个进程各记一份，每份都没超，合起来是 N 倍预算。
            -- **按进程计的预算不是预算。**
            --
            -- 为什么金额列是 INTEGER 而不是 REAL：累加在 SQL 里做，REAL 累加
            -- 会漂（实测 0.1+0.2 存回来是 0.30000000000000004）。在 Python 侧
            -- 用 Decimal 只能保证"读出来是 Decimal"，管不住 SQL 里的加法。
            -- 所以金额以 **纳美元（1e-9 USD）整数**存储，SQL 加法完全精确；
            -- 单位选纳而不是微，是为了让一次很便宜的调用（约 1.5e-5 USD）
            -- 也不会被舍入成 0 —— 舍成 0 就回到了"成本静默变成零"。
            -- int64 上限对应 9.2e9 美元，不存在溢出问题。
            --
            -- spend_date 是 PRIMARY KEY（UTC 日期字符串）：累加走 UPSERT
            -- 单语句完成，先 SELECT 再 UPDATE 在并发下会丢记账。
            CREATE TABLE IF NOT EXISTS llm_spend_daily (
                spend_date        TEXT PRIMARY KEY,
                cost_nano_usd     INTEGER NOT NULL DEFAULT 0,
                calls             INTEGER NOT NULL DEFAULT 0,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS narratives (
                sector      TEXT PRIMARY KEY,
                aliases     TEXT,
                base_heat   REAL,
                stage       TEXT,
                momentum    REAL,
                updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dedup_keys (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key   TEXT UNIQUE NOT NULL,
                project_id  TEXT NOT NULL,
                name_raw    TEXT NOT NULL,
                sector_raw  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS prompt_versions (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_name  TEXT NOT NULL,
                prompt_key  TEXT NOT NULL,
                version     TEXT NOT NULL,
                content     TEXT NOT NULL,
                is_default  INTEGER DEFAULT 0,
                created_by  TEXT NOT NULL,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 归档运行历史：每次 RawDataArchiver.run() 记一行。
            -- 此前归档只有手动脚本、跑完不留痕，前端 /archive 页因此只能显示
            -- "暂无运行历史接口"。
            CREATE TABLE IF NOT EXISTS archive_runs (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at              TIMESTAMP NOT NULL,
                finished_at             TIMESTAMP NOT NULL,
                duration_ms             INTEGER DEFAULT 0,
                trigger                 TEXT NOT NULL,
                dry_run                 INTEGER DEFAULT 0,
                status                  TEXT NOT NULL,
                raw_archived            INTEGER DEFAULT 0,
                unprocessed_archived    INTEGER DEFAULT 0,
                signals_archived        INTEGER DEFAULT 0,
                logs_deleted            INTEGER DEFAULT 0,
                raw_archive_pruned      INTEGER DEFAULT 0,
                signals_archive_pruned  INTEGER DEFAULT 0,
                error_message           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(score);
            CREATE INDEX IF NOT EXISTS idx_projects_label ON projects(label);
            CREATE INDEX IF NOT EXISTS idx_projects_sector ON projects(sector);
            CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at);
            CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id);
            CREATE INDEX IF NOT EXISTS idx_logs_project ON logs(project_id);
            CREATE INDEX IF NOT EXISTS idx_data_sources_enabled ON data_sources(enabled);
            CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(sync_status);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_dedup ON raw_projects(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_unprocessed ON raw_projects(processed) WHERE processed = 0;
            CREATE INDEX IF NOT EXISTS idx_raw_projects_source ON raw_projects(source_id);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_discovered ON raw_projects(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signals_project ON project_signals(project_id);
            CREATE INDEX IF NOT EXISTS idx_signals_dedup ON project_signals(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_signals_type ON project_signals(signal_type, signal_source);
            CREATE INDEX IF NOT EXISTS idx_signals_captured ON project_signals(captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_source ON collection_logs(source_id);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_started ON collection_logs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_status ON collection_logs(status);
            CREATE INDEX IF NOT EXISTS idx_archive_dedup ON raw_projects_archive(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_archive_discovered ON raw_projects_archive(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_archived_at ON raw_projects_archive(archived_at);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_project ON project_signals_archive(project_id);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_captured ON project_signals_archive(captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_archived_at ON project_signals_archive(archived_at);
            CREATE INDEX IF NOT EXISTS idx_archive_runs_started ON archive_runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_project ON feedback(project_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON feedback(outcome) WHERE outcome IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_interactions_project ON interactions(project_id);
            CREATE INDEX IF NOT EXISTS idx_interactions_status ON interactions(status);
            CREATE INDEX IF NOT EXISTS idx_interactions_started ON interactions(started_at);
            CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_project ON opportunity_evidence(project_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_factor ON opportunity_evidence(project_id, factor_key, verification_status);
            CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_latest ON opportunity_assessments(project_id, profile_version, scored_at DESC);
            CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_label ON opportunity_assessments(public_label, expires_at);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_run_source ON opportunity_economic_snapshots(run_id, source_id);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_identity ON opportunity_economic_snapshots(source_id, dedup_key);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_collected ON opportunity_economic_snapshots(collected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_watchlist_project ON watchlist(project_id);
            CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
            CREATE INDEX IF NOT EXISTS idx_weight_changelog_created ON weight_changelog(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_signal ON feedback(signal);
            CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine(status);
            CREATE INDEX IF NOT EXISTS idx_quarantine_reason ON quarantine(failure_reason);
            CREATE INDEX IF NOT EXISTS idx_quarantine_created ON quarantine(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_project_history_project ON project_history(project_id);
            CREATE INDEX IF NOT EXISTS idx_project_history_run ON project_history(run_id);
            CREATE INDEX IF NOT EXISTS idx_project_history_created ON project_history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs("user");
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_eval_date ON llm_eval_changelog(eval_date DESC);
            CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);
            CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
            CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_narratives_stage ON narratives(stage);
            CREATE INDEX IF NOT EXISTS idx_dedup_key ON dedup_keys(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_dedup_project ON dedup_keys(project_id);
            CREATE INDEX IF NOT EXISTS idx_prompt_agent ON prompt_versions(agent_name);
            CREATE INDEX IF NOT EXISTS idx_prompt_version ON prompt_versions(agent_name, version);
    """


def _postgres_ddl() -> str:
    # Same schema; SERIAL for auto ids; INTEGER flags kept for app compatibility
    return """
            CREATE TABLE IF NOT EXISTS projects (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                url             TEXT,
                sector          TEXT,
                stage           TEXT,
                score           INTEGER,
                label           TEXT,
                recommendation  TEXT,
                confidence      DOUBLE PRECISION,
                weight_version  TEXT,
                veto            TEXT,
                reason          TEXT,
                narrative_json  TEXT,
                team_json       TEXT,
                risk_json       TEXT,
                tokenomics_json TEXT,
                raw_signals     TEXT,
                sub_scores      TEXT,
                meta            TEXT,
                source          TEXT,
                raw_signals_hash TEXT,
                fetched_at      TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS logs (
                id          SERIAL PRIMARY KEY,
                run_id      TEXT NOT NULL,
                project_id  TEXT,
                agent_name  TEXT,
                input       TEXT,
                output      TEXT,
                error       TEXT,
                duration_ms INTEGER,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS data_sources (
                source_id       TEXT PRIMARY KEY,
                source_type     TEXT NOT NULL,
                source_name     TEXT NOT NULL,
                enabled         INTEGER DEFAULT 1,
                last_sync       TIMESTAMP,
                sync_status     TEXT DEFAULT 'idle',
                api_calls_today INTEGER DEFAULT 0,
                api_limit       INTEGER,
                config          TEXT,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS raw_projects (
                raw_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                dedup_key       TEXT NOT NULL,
                raw_data        TEXT NOT NULL,
                discovered_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                processed       INTEGER DEFAULT 0,
                processed_at    TIMESTAMP,
                project_id      TEXT,
                discovery_score DOUBLE PRECISION DEFAULT 0.0,
                quarantined     INTEGER DEFAULT 0,
                quarantine_reason TEXT
            );

            CREATE TABLE IF NOT EXISTS project_signals (
                signal_id       TEXT PRIMARY KEY,
                project_id      TEXT,
                dedup_key       TEXT,
                signal_type     TEXT NOT NULL,
                signal_source   TEXT NOT NULL,
                signal_data     TEXT NOT NULL,
                signal_strength DOUBLE PRECISION DEFAULT 0.0,
                captured_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS collection_logs (
                log_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                started_at      TIMESTAMP NOT NULL,
                finished_at     TIMESTAMP,
                items_collected INTEGER DEFAULT 0,
                items_new       INTEGER DEFAULT 0,
                items_duplicate INTEGER DEFAULT 0,
                status          TEXT,
                error_message   TEXT
            );

            CREATE TABLE IF NOT EXISTS raw_projects_archive (
                raw_id          TEXT PRIMARY KEY,
                source_id       TEXT NOT NULL,
                dedup_key       TEXT NOT NULL,
                raw_data        TEXT NOT NULL,
                discovered_at   TIMESTAMP,
                processed       INTEGER DEFAULT 0,
                processed_at    TIMESTAMP,
                project_id      TEXT,
                discovery_score DOUBLE PRECISION DEFAULT 0.0,
                archived_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS project_signals_archive (
                signal_id       TEXT PRIMARY KEY,
                project_id      TEXT,
                dedup_key       TEXT,
                signal_type     TEXT NOT NULL,
                signal_source   TEXT NOT NULL,
                signal_data     TEXT NOT NULL,
                signal_strength DOUBLE PRECISION DEFAULT 0.0,
                captured_at     TIMESTAMP,
                archived_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id          SERIAL PRIMARY KEY,
                project_id  TEXT NOT NULL,
                user_id     TEXT,
                signal      TEXT NOT NULL,
                note        TEXT,
                outcome     TEXT,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS events (
                id          SERIAL PRIMARY KEY,
                project_id  TEXT,
                user_id     TEXT,
                event_type  TEXT NOT NULL,
                detail      TEXT,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interactions (
                id              SERIAL PRIMARY KEY,
                project_id      TEXT NOT NULL,
                user_id         TEXT,
                status          TEXT NOT NULL DEFAULT 'planned',
                started_at      TEXT,
                ended_at        TEXT,
                cost_usd        DOUBLE PRECISION,
                profit_usd      DOUBLE PRECISION,
                hours_spent     DOUBLE PRECISION,
                activities      TEXT,
                note            TEXT,
                outcome         TEXT,
                score_at_start  INTEGER,
                label_at_start  TEXT,
                wallet_cohort_id TEXT,
                wallet_count INTEGER DEFAULT 1,
                actual_hard_cost_usd DOUBLE PRECISION,
                actual_time_minutes INTEGER,
                eligibility_result TEXT,
                survival_result TEXT,
                disqualification_reason TEXT,
                reward_received_usd DOUBLE PRECISION,
                claim_cost_usd DOUBLE PRECISION,
                opportunity_assessment_id TEXT,
                opportunity_model_version TEXT,
                opportunity_profile_version TEXT,
                outcome_observed_at TIMESTAMPTZ,
                created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_evidence (
                evidence_id         TEXT PRIMARY KEY,
                project_id          TEXT NOT NULL,
                factor_key          TEXT NOT NULL,
                value_json          TEXT NOT NULL,
                value_type          TEXT NOT NULL,
                observation_type    TEXT NOT NULL,
                source_url          TEXT NOT NULL,
                source_type         TEXT NOT NULL,
                source_grade        TEXT NOT NULL,
                observed_at         TIMESTAMPTZ NOT NULL,
                effective_at        TIMESTAMPTZ,
                expires_at          TIMESTAMPTZ,
                verification_status TEXT NOT NULL,
                independence_group  TEXT NOT NULL,
                raw_snapshot_ref    TEXT,
                supersedes_evidence_id TEXT,
                created_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_assessments (
                assessment_id      TEXT PRIMARY KEY,
                project_id         TEXT NOT NULL,
                model_version      TEXT NOT NULL,
                profile_version    TEXT NOT NULL,
                assessment_json    TEXT NOT NULL,
                decision_status    TEXT NOT NULL,
                public_label       TEXT NOT NULL,
                decision_value     DOUBLE PRECISION,
                overall_confidence DOUBLE PRECISION NOT NULL,
                scored_at          TIMESTAMPTZ NOT NULL,
                review_at          TIMESTAMPTZ,
                expires_at         TIMESTAMPTZ NOT NULL,
                created_at         TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS opportunity_economic_snapshots (
                snapshot_id        TEXT PRIMARY KEY,
                schema_version     TEXT NOT NULL,
                run_id             TEXT NOT NULL,
                source_id          TEXT NOT NULL,
                dedup_key          TEXT NOT NULL CHECK(length(trim(dedup_key))>0),
                provider_entity_id TEXT NOT NULL,
                payload_sha256     TEXT NOT NULL,
                payload_json       TEXT NOT NULL,
                source_url         TEXT NOT NULL,
                collected_at       TIMESTAMPTZ NOT NULL
            );

            -- 用户 Watchlist（ADR-008 V2）
            CREATE TABLE IF NOT EXISTS watchlist (
                id          SERIAL PRIMARY KEY,
                project_id  TEXT NOT NULL,
                user_id     TEXT,
                note        TEXT,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(project_id, user_id)
            );

            -- 通知已读状态（按用户 + 稳定 notification_id）
            CREATE TABLE IF NOT EXISTS notification_reads (
                user_id          TEXT NOT NULL,
                notification_id  TEXT NOT NULL,
                read_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, notification_id)
            );
            CREATE INDEX IF NOT EXISTS idx_notification_reads_user
                ON notification_reads(user_id);

            -- 决策推派出站日志（ACTION_LOOP_DESIGN.md §2.5）
            -- (event_key, channel) 唯一：同事件同通道天然去重，重发靠 UPSERT 忽略。
            CREATE TABLE IF NOT EXISTS notify_log (
                id          SERIAL PRIMARY KEY,
                event_type  TEXT NOT NULL,
                event_key   TEXT NOT NULL,
                channel     TEXT NOT NULL,
                title       TEXT NOT NULL,
                body        TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                attempts    INTEGER NOT NULL DEFAULT 0,
                last_error  TEXT,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                sent_at     TIMESTAMPTZ,
                UNIQUE (event_key, channel)
            );
            CREATE INDEX IF NOT EXISTS idx_notify_log_status
                ON notify_log(status, created_at);

            -- 参与流水（ACTION_LOOP_DESIGN.md §3，F2）
            -- plan/task 两级：plan 是「我在参与这个项目」，task 是具体动作。
            -- user_id 来自 token 身份（get_current_user），不接受请求体自报。
            -- 刻意不设 SQL 级外键（全仓约定，见 opportunity 的同类测试）：
            -- 级联删除由路由层显式先删 task 再删 plan 保证。
            --
            CREATE TABLE IF NOT EXISTS participation_plans (
                id          SERIAL PRIMARY KEY,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'active',
                note        TEXT,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                updated_at  TIMESTAMPTZ,
                UNIQUE (user_id, project_id)
            );

            CREATE TABLE IF NOT EXISTS participation_tasks (
                id           SERIAL PRIMARY KEY,
                plan_id      INTEGER NOT NULL,
                ref          TEXT,
                title        TEXT NOT NULL,
                kind         TEXT NOT NULL DEFAULT 'other',
                status       TEXT NOT NULL DEFAULT 'todo',
                url          TEXT,
                due_at       TIMESTAMPTZ,
                note         TEXT,
                completed_at TIMESTAMPTZ,
                created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_participation_tasks_plan
                ON participation_tasks(plan_id, status);

            -- 收益台账（ACTION_LOOP_DESIGN.md §4，F3）
            -- 同 SQLite 侧口径：投入/产出分表，source 区分 live 与 backtest，
            -- 校准时分开统计。金额人工录入，不做链上取价。
            CREATE TABLE IF NOT EXISTS roi_entries (
                id          SERIAL PRIMARY KEY,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                kind        TEXT NOT NULL,
                amount_usd  DOUBLE PRECISION,
                hours       DOUBLE PRECISION,
                note        TEXT,
                recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_roi_entries_user_project
                ON roi_entries(user_id, project_id);

            CREATE TABLE IF NOT EXISTS roi_outcomes (
                id          SERIAL PRIMARY KEY,
                user_id     TEXT NOT NULL,
                project_id  TEXT NOT NULL,
                event       TEXT NOT NULL,
                amount_usd  DOUBLE PRECISION,
                tokens      DOUBLE PRECISION,
                tx_hash     TEXT,
                source      TEXT NOT NULL DEFAULT 'manual',
                recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_roi_outcomes_user_project
                ON roi_outcomes(user_id, project_id);

            -- 权重校准变更日志（WEIGHT_CALIBRATION.md §7）
            CREATE TABLE IF NOT EXISTS weight_changelog (
                id              SERIAL PRIMARY KEY,
                from_version    TEXT,
                to_version      TEXT,
                weights_json    TEXT NOT NULL,
                sample_size     INTEGER,
                metrics_json    TEXT,
                triggered_by    TEXT,
                status          TEXT DEFAULT 'candidate',
                created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            -- ── V2 新表（§5.4） ──────────────────────
            CREATE TABLE IF NOT EXISTS quarantine (
                id              SERIAL PRIMARY KEY,
                project_id      TEXT,
                raw_data        TEXT NOT NULL,
                failure_reason  TEXT NOT NULL,
                severity        TEXT DEFAULT 'warning',
                status          TEXT DEFAULT 'pending',
                resolved_at     TIMESTAMPTZ,
                created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS project_history (
                id              SERIAL PRIMARY KEY,
                project_id      TEXT NOT NULL,
                run_id          TEXT NOT NULL,
                score           INTEGER,
                label           TEXT,
                stage           TEXT,
                weight_version  TEXT,
                snapshot        TEXT NOT NULL,
                created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS audit_logs (
                id          SERIAL PRIMARY KEY,
                action      TEXT NOT NULL,
                "user"      TEXT NOT NULL,
                detail      TEXT,
                ip          TEXT,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS llm_eval_changelog (
                id              SERIAL PRIMARY KEY,
                eval_date       TIMESTAMPTZ NOT NULL,
                sample_count    INTEGER NOT NULL,
                rule_accuracy   REAL NOT NULL,
                llm_accuracy    REAL NOT NULL,
                llm_cost_usd    REAL NOT NULL,
                decision        TEXT NOT NULL,
                detail          TEXT,
                created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS metrics (
                id          SERIAL PRIMARY KEY,
                run_id      TEXT NOT NULL,
                metric_name TEXT NOT NULL,
                metric_value REAL NOT NULL,
                detail      TEXT,
                timestamp   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            -- LLM 日花费账本（迁移 0004）。说明见 SQLite 分支的同名表注释。
            -- cost_nano_usd 用 BIGINT：纳美元整数，int64 上限约 9.2e9 美元。
            CREATE TABLE IF NOT EXISTS llm_spend_daily (
                spend_date        TEXT PRIMARY KEY,
                cost_nano_usd     BIGINT NOT NULL DEFAULT 0,
                calls             INTEGER NOT NULL DEFAULT 0,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                updated_at        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS narratives (
                sector      TEXT PRIMARY KEY,
                aliases     TEXT,
                base_heat   REAL,
                stage       TEXT,
                momentum    REAL,
                updated_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS dedup_keys (
                id          SERIAL PRIMARY KEY,
                dedup_key   TEXT UNIQUE NOT NULL,
                project_id  TEXT NOT NULL,
                name_raw    TEXT NOT NULL,
                sector_raw  TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS prompt_versions (
                id          SERIAL PRIMARY KEY,
                agent_name  TEXT NOT NULL,
                prompt_key  TEXT NOT NULL,
                version     TEXT NOT NULL,
                content     TEXT NOT NULL,
                is_default  INTEGER DEFAULT 0,
                created_by  TEXT NOT NULL,
                created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            );

            -- 归档运行历史（见 SQLite 分支同名表的注释）
            CREATE TABLE IF NOT EXISTS archive_runs (
                id                      SERIAL PRIMARY KEY,
                started_at              TIMESTAMPTZ NOT NULL,
                finished_at             TIMESTAMPTZ NOT NULL,
                duration_ms             INTEGER DEFAULT 0,
                trigger                 TEXT NOT NULL,
                dry_run                 INTEGER DEFAULT 0,
                status                  TEXT NOT NULL,
                raw_archived            INTEGER DEFAULT 0,
                unprocessed_archived    INTEGER DEFAULT 0,
                signals_archived        INTEGER DEFAULT 0,
                logs_deleted            INTEGER DEFAULT 0,
                raw_archive_pruned      INTEGER DEFAULT 0,
                signals_archive_pruned  INTEGER DEFAULT 0,
                error_message           TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(score);
            CREATE INDEX IF NOT EXISTS idx_projects_label ON projects(label);
            CREATE INDEX IF NOT EXISTS idx_projects_sector ON projects(sector);
            CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at);
            CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id);
            CREATE INDEX IF NOT EXISTS idx_logs_project ON logs(project_id);
            CREATE INDEX IF NOT EXISTS idx_data_sources_enabled ON data_sources(enabled);
            CREATE INDEX IF NOT EXISTS idx_data_sources_status ON data_sources(sync_status);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_dedup ON raw_projects(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_unprocessed ON raw_projects(processed) WHERE processed = 0;
            CREATE INDEX IF NOT EXISTS idx_raw_projects_source ON raw_projects(source_id);
            CREATE INDEX IF NOT EXISTS idx_raw_projects_discovered ON raw_projects(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signals_project ON project_signals(project_id);
            CREATE INDEX IF NOT EXISTS idx_signals_dedup ON project_signals(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_signals_type ON project_signals(signal_type, signal_source);
            CREATE INDEX IF NOT EXISTS idx_signals_captured ON project_signals(captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_source ON collection_logs(source_id);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_started ON collection_logs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_collection_logs_status ON collection_logs(status);
            CREATE INDEX IF NOT EXISTS idx_archive_dedup ON raw_projects_archive(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_archive_discovered ON raw_projects_archive(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_archive_archived_at ON raw_projects_archive(archived_at);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_project ON project_signals_archive(project_id);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_captured ON project_signals_archive(captured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_signals_archive_archived_at ON project_signals_archive(archived_at);
            CREATE INDEX IF NOT EXISTS idx_archive_runs_started ON archive_runs(started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_project ON feedback(project_id);
            CREATE INDEX IF NOT EXISTS idx_feedback_outcome ON feedback(outcome) WHERE outcome IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id);
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
            CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_interactions_project ON interactions(project_id);
            CREATE INDEX IF NOT EXISTS idx_interactions_status ON interactions(status);
            CREATE INDEX IF NOT EXISTS idx_interactions_started ON interactions(started_at);
            CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_project ON opportunity_evidence(project_id, observed_at DESC);
            CREATE INDEX IF NOT EXISTS idx_opportunity_evidence_factor ON opportunity_evidence(project_id, factor_key, verification_status);
            CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_latest ON opportunity_assessments(project_id, profile_version, scored_at DESC);
            CREATE INDEX IF NOT EXISTS idx_opportunity_assessment_label ON opportunity_assessments(public_label, expires_at);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_run_source ON opportunity_economic_snapshots(run_id, source_id);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_identity ON opportunity_economic_snapshots(source_id, dedup_key);
            CREATE INDEX IF NOT EXISTS idx_opportunity_economic_snapshots_collected ON opportunity_economic_snapshots(collected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_watchlist_project ON watchlist(project_id);
            CREATE INDEX IF NOT EXISTS idx_watchlist_user ON watchlist(user_id);
            CREATE INDEX IF NOT EXISTS idx_weight_changelog_created ON weight_changelog(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_feedback_signal ON feedback(signal);
            CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine(status);
            CREATE INDEX IF NOT EXISTS idx_quarantine_reason ON quarantine(failure_reason);
            CREATE INDEX IF NOT EXISTS idx_quarantine_created ON quarantine(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_project_history_project ON project_history(project_id);
            CREATE INDEX IF NOT EXISTS idx_project_history_run ON project_history(run_id);
            CREATE INDEX IF NOT EXISTS idx_project_history_created ON project_history(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
            CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs("user");
            CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_llm_eval_date ON llm_eval_changelog(eval_date DESC);
            CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);
            CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
            CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_narratives_stage ON narratives(stage);
            CREATE INDEX IF NOT EXISTS idx_dedup_key ON dedup_keys(dedup_key);
            CREATE INDEX IF NOT EXISTS idx_dedup_project ON dedup_keys(project_id);
            CREATE INDEX IF NOT EXISTS idx_prompt_agent ON prompt_versions(agent_name);
            CREATE INDEX IF NOT EXISTS idx_prompt_version ON prompt_versions(agent_name, version);
    """


def _as_db_connection(conn: Any) -> tuple[DbConnection, bool]:
    """Normalize optional conn to DbConnection. Returns (conn, owns_lifecycle)."""
    if conn is None:
        return get_connection(), True
    if isinstance(conn, DbConnection):
        return conn, False
    # Legacy: raw sqlite3.Connection from tests
    if isinstance(conn, sqlite3.Connection):
        if conn.row_factory is None:
            conn.row_factory = sqlite3.Row
        return DbConnection(conn, kind="sqlite"), False
    raise TypeError(f"Unsupported connection type: {type(conn)}")


def init_db(conn: Any = None) -> None:
    """Idempotent schema init for SQLite or PostgreSQL."""
    db, should_close = _as_db_connection(conn)

    try:
        if db.kind == "postgres":
            db.execute(
                "SELECT pg_advisory_xact_lock(?)",
                (POSTGRES_INIT_ADVISORY_LOCK_ID,),
            )
        ddl = _postgres_ddl() if db.kind == "postgres" else _sqlite_ddl()
        db.executescript(ddl)

        _add_column_if_not_exists(db, "projects", "discovery_source", "TEXT DEFAULT 'manual'")
        _add_column_if_not_exists(db, "projects", "discovered_at", "TIMESTAMP")
        _add_column_if_not_exists(db, "projects", "auto_discovered", "INTEGER DEFAULT 0")
        _add_column_if_not_exists(db, "projects", "signal_count", "INTEGER DEFAULT 0")
        # 子分快照（WEIGHT_CALIBRATION §4.3 步骤 1：离线重加权需要"固定 Agent 子分"）。
        # 不复用 raw_signals：那一列存的是采集到的**输入**信号（scripts/seed.py 与
        # raw_signals_hash 均按此语义写入），子分是**输出**，两者形状不兼容。
        _add_column_if_not_exists(db, "projects", "sub_scores", "TEXT")
        # 资格门否决原因（ADR-015）。CREATE TABLE IF NOT EXISTS 不会给既有库补列，
        # 漏登记这行会让所有已存在的开发/生产库在 save 时报
        # "table projects has no column named veto"（评分成功但落库失败 → run 变 failed）。
        _add_column_if_not_exists(db, "projects", "veto", "TEXT")
        _add_column_if_not_exists(db, "raw_projects", "quarantined", "INTEGER DEFAULT 0")
        _add_column_if_not_exists(db, "raw_projects", "quarantine_reason", "TEXT")

        interaction_columns = {
            "wallet_cohort_id": "TEXT",
            "wallet_count": "INTEGER DEFAULT 1",
            "actual_hard_cost_usd": ("DOUBLE PRECISION" if db.kind == "postgres" else "REAL"),
            "actual_time_minutes": "INTEGER",
            "eligibility_result": "TEXT",
            "survival_result": "TEXT",
            "disqualification_reason": "TEXT",
            "reward_received_usd": ("DOUBLE PRECISION" if db.kind == "postgres" else "REAL"),
            "claim_cost_usd": ("DOUBLE PRECISION" if db.kind == "postgres" else "REAL"),
            "opportunity_assessment_id": "TEXT",
            "opportunity_model_version": "TEXT",
            "opportunity_profile_version": "TEXT",
            "outcome_observed_at": ("TIMESTAMPTZ" if db.kind == "postgres" else "TIMESTAMP"),
        }
        for column, definition in interaction_columns.items():
            _add_column_if_not_exists(db, "interactions", column, definition)
        _add_column_if_not_exists(db, "opportunity_evidence", "supersedes_evidence_id", "TEXT")

        db.executescript("""
            CREATE INDEX IF NOT EXISTS idx_projects_auto_discovered ON projects(auto_discovered);
            CREATE INDEX IF NOT EXISTS idx_projects_discovery_source ON projects(discovery_source);
            CREATE INDEX IF NOT EXISTS idx_projects_discovered_at ON projects(discovered_at DESC);
            CREATE INDEX IF NOT EXISTS idx_raw_quarantined ON raw_projects(quarantined);
        """)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        if should_close:
            db.close()


def dict_from_row(row: Any) -> dict[str, Any]:
    """Convert a DB row to a plain dict."""
    if row is None:
        return {}
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def scalar(row: Any, default: Any = 0) -> Any:
    """Read first column from a fetchone() result (sqlite Row or dict)."""
    if row is None:
        return default
    if isinstance(row, dict):
        return next(iter(row.values()), default)
    try:
        return row[0]
    except Exception:
        return default


def insert_returning_id(conn: Any, sql: str, params: Iterable[Any], *, id_column: str = "id") -> Any:
    """Execute an INSERT and return the new row's id on both SQLite and Postgres.

    psycopg3 dropped ``cursor.lastrowid``; use ``RETURNING`` where available and
    fall back to ``last_insert_rowid()`` on ancient SQLite runtimes.
    """
    kind = getattr(conn, "kind", "sqlite")
    supports_returning = kind == "postgres" or sqlite3.sqlite_version_info >= (3, 35, 0)
    if supports_returning:
        cursor = conn.execute(sql.rstrip().rstrip(";") + f" RETURNING {id_column}", tuple(params))
        return scalar(cursor.fetchone(), None)
    cursor = conn.execute(sql, tuple(params))
    if kind == "postgres":  # pragma: no cover - PG always supports RETURNING
        return None
    return scalar(conn.execute("SELECT last_insert_rowid()").fetchone(), None)
