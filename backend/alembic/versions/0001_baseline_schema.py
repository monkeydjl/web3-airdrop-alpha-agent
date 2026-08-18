"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-08-13

将 db.py init_db() 产出的当前 schema 固化为 Alembic baseline。
直接复用 init_db() 作为单一真相源，保证迁移产物与现状完全一致：
- 14 张表（projects / logs / data_sources / raw_projects / project_signals /
  collection_logs / raw_projects_archive / project_signals_archive / feedback /
  events / interactions / opportunity_evidence / opportunity_assessments /
  opportunity_economic_snapshots）
- 40+ 索引（含部分索引 WHERE 子句）
- opportunity_economic_snapshots.dedup_key CHECK 约束
- init_db() 的 _add_column_if_not_exists 补充列（projects.discovery_source 等）
- init_db() 第二个 executescript 的 4 个补充索引

init_db() 幂等（CREATE TABLE/INDEX IF NOT EXISTS + 条件 ADD COLUMN），
在空库与已有库上均安全。
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# downgrade 时按依赖逆序删除（无外键约束，顺序仅作保险）
_TABLES = [
    "prompt_versions",
    "dedup_keys",
    "narratives",
    "metrics",
    "llm_eval_changelog",
    "audit_logs",
    "project_history",
    "quarantine",
    "opportunity_economic_snapshots",
    "opportunity_assessments",
    "opportunity_evidence",
    "interactions",
    "events",
    "feedback",
    "weight_changelog",
    "watchlist",
    "project_signals_archive",
    "raw_projects_archive",
    "collection_logs",
    "project_signals",
    "raw_projects",
    "data_sources",
    "logs",
    "projects",
]


def upgrade() -> None:
    """建立与 db.py init_db() 一致的 baseline schema。"""
    # 直接复用 init_db()：DDL + 条件补列 + 补充索引，双后端一致。
    # env.py 已确保 alembic 与 init_db() 指向同一库（经 settings 解析）。
    from app.db import init_db

    init_db()


def downgrade() -> None:
    """回滚 baseline：删除全部用户表（索引随表自动删除）。"""
    from sqlalchemy import text

    bind = op.get_bind()
    for table in _TABLES:
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
