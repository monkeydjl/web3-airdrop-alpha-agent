"""archive_runs table + archived_at indexes

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-22

补上归档子系统缺的两块：

1. `archive_runs` 表 —— 归档此前只有手动脚本，跑完不留任何记录，前端
   `/archive` 页因此只能显示"暂无运行历史接口"。现在每次 `RawDataArchiver.run()`
   记一行（触发方式 / 耗时 / 六个分项行数 / 成功或失败）。

2. `archived_at` 索引 —— 归档表自身的保留期清理（DATABASE_DDL.md §6 写了
   180/365 天，此前零实现）需要按 `archived_at` 删除，没有索引会全表扫。

Reference:
- DATABASE_DDL.md §6 数据保留策略
- app/archive.py RawDataArchiver
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# SQLite DDL；PG 分支在 upgrade() 里换 SERIAL/TIMESTAMPTZ
_SQLITE_SQL = """
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
"""

_PG_SQL = """
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
"""

_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_archive_runs_started ON archive_runs(started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_archive_archived_at ON raw_projects_archive(archived_at)",
    ("CREATE INDEX IF NOT EXISTS idx_signals_archive_archived_at ON project_signals_archive(archived_at)"),
]

_DROP_INDEXES = [
    "idx_signals_archive_archived_at",
    "idx_archive_archived_at",
    "idx_archive_runs_started",
]


def upgrade() -> None:
    """创建 archive_runs 表 + archived_at 索引。"""
    from sqlalchemy import text

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    bind.execute(text((_PG_SQL if is_pg else _SQLITE_SQL).strip()))
    for stmt in _INDEXES:
        bind.execute(text(stmt))


def downgrade() -> None:
    """回滚 archive_runs 表 + 索引。"""
    from sqlalchemy import text

    bind = op.get_bind()
    for idx in _DROP_INDEXES:
        bind.execute(text(f"DROP INDEX IF EXISTS {idx}"))
    bind.execute(text("DROP TABLE IF EXISTS archive_runs"))
