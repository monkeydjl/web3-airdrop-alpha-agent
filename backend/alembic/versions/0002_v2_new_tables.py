"""V2 new tables: governance/observability/dimension tables

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-15

新增 §5.4 定义的 V2 表：
- quarantine (§5.4.3 脏数据隔离)
- project_history (§5.4.4 项目演化快照)
- audit_logs (§5.4.7 审计日志)
- llm_eval_changelog (§5.4.7 LLM 评估记录)
- metrics (§5.4.7 数据质量指标)
- narratives (§5.4.6 赛道元数据维表)
- dedup_keys (§5.4.8 去重键映射)
- prompt_versions (§5.4.9 Prompt 版本管理)

补全 feedback 表缺失索引（idx_feedback_signal / idx_feedback_created）。

Reference:
- DATABASE_DDL.md §2.4–§2.12
- ENGINEERING_ROADMAP.md §5.4
- V2_TASKS.md E1/E2/E3
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite DDL（也用于 PG，TIMESTAMP 语义一致）
_NEW_TABLES_SQL = """
-- ============================================
-- quarantine 表（脏数据隔离，§5.4.3）
-- ============================================
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
CREATE INDEX IF NOT EXISTS idx_quarantine_status ON quarantine(status);
CREATE INDEX IF NOT EXISTS idx_quarantine_reason ON quarantine(failure_reason);
CREATE INDEX IF NOT EXISTS idx_quarantine_created ON quarantine(created_at DESC);

-- ============================================
-- project_history 表（项目历史快照，§5.4.4）
-- ============================================
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
CREATE INDEX IF NOT EXISTS idx_project_history_project ON project_history(project_id);
CREATE INDEX IF NOT EXISTS idx_project_history_run ON project_history(run_id);
CREATE INDEX IF NOT EXISTS idx_project_history_created ON project_history(created_at DESC);

-- ============================================
-- audit_logs 表（审计日志，§5.4.7）
-- ============================================
CREATE TABLE IF NOT EXISTS audit_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT NOT NULL,
    "user"      TEXT NOT NULL,
    detail      TEXT,
    ip          TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs("user");
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_logs(created_at DESC);

-- ============================================
-- llm_eval_changelog 表（LLM 评估记录，§5.4.7）
-- ============================================
CREATE TABLE IF NOT EXISTS llm_eval_changelog (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    eval_date       TIMESTAMP NOT NULL,
    sample_count    INTEGER NOT NULL,
    rule_accuracy   REAL NOT NULL,
    llm_accuracy    REAL NOT NULL,
    llm_cost_usd    REAL NOT NULL,
    decision        TEXT NOT NULL,
    detail           TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_llm_eval_date ON llm_eval_changelog(eval_date DESC);

-- ============================================
-- metrics 表（数据质量指标，§5.4.7）
-- ============================================
CREATE TABLE IF NOT EXISTS metrics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id      TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL NOT NULL,
    detail      TEXT,
    timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_metrics_run_id ON metrics(run_id);
CREATE INDEX IF NOT EXISTS idx_metrics_name ON metrics(metric_name);
CREATE INDEX IF NOT EXISTS idx_metrics_timestamp ON metrics(timestamp DESC);

-- ============================================
-- narratives 维表（赛道元数据，§5.4.6）
-- ============================================
CREATE TABLE IF NOT EXISTS narratives (
    sector      TEXT PRIMARY KEY,
    aliases     TEXT,
    base_heat   REAL,
    stage       TEXT,
    momentum    REAL,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_narratives_stage ON narratives(stage);

-- ============================================
-- dedup_keys 表（去重键映射，§5.4.8）
-- ============================================
CREATE TABLE IF NOT EXISTS dedup_keys (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key   TEXT UNIQUE NOT NULL,
    project_id  TEXT NOT NULL,
    name_raw    TEXT NOT NULL,
    sector_raw  TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_dedup_key ON dedup_keys(dedup_key);
CREATE INDEX IF NOT EXISTS idx_dedup_project ON dedup_keys(project_id);

-- ============================================
-- prompt_versions 表（Prompt 版本管理，§5.4.9）
-- ============================================
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
CREATE INDEX IF NOT EXISTS idx_prompt_agent ON prompt_versions(agent_name);
CREATE INDEX IF NOT EXISTS idx_prompt_version ON prompt_versions(agent_name, version);

-- 补全 feedback 表缺失索引
CREATE INDEX IF NOT EXISTS idx_feedback_signal ON feedback(signal);
CREATE INDEX IF NOT EXISTS idx_feedback_created ON feedback(created_at DESC);

-- ============================================
-- notification_reads 表（通知已读状态，按用户 + notification_id）
-- ============================================
CREATE TABLE IF NOT EXISTS notification_reads (
    user_id          TEXT NOT NULL,
    notification_id  TEXT NOT NULL,
    read_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, notification_id)
);
CREATE INDEX IF NOT EXISTS idx_notification_reads_user ON notification_reads(user_id);
"""

# downgrade 时按依赖逆序删除
_DROP_TABLES = [
    "notification_reads",
    "prompt_versions",
    "dedup_keys",
    "narratives",
    "metrics",
    "llm_eval_changelog",
    "audit_logs",
    "project_history",
    "quarantine",
]

_DROP_INDEXES = [
    "idx_notification_reads_user",
    "idx_feedback_created",
    "idx_feedback_signal",
]


def upgrade() -> None:
    """创建 V2 新表 + 补全索引。"""
    from sqlalchemy import text

    bind = op.get_bind()

    # 按分号拆分为独立语句，逐条执行（兼容 SQLite + PostgreSQL）
    for stmt in _NEW_TABLES_SQL.split(";"):
        stmt = stmt.strip()
        # 跳过空语句和纯注释行
        if stmt and not stmt.startswith("--"):
            # 去掉前导注释行
            lines = [l for l in stmt.split("\n") if not l.strip().startswith("--")]
            clean = "\n".join(lines).strip()
            if clean:
                bind.execute(text(clean))


def downgrade() -> None:
    """回滚 V2 新表 + 删除补全索引。"""
    from sqlalchemy import text

    bind = op.get_bind()
    for idx in _DROP_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {idx}"))
    for table in _DROP_TABLES:
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
