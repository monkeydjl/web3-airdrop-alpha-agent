"""V3 API Keys 表（api_keys）

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19

Reference:
- ADR-008-user-system.md §3 核心数据模型
- ENGINEERING_ROADMAP.md §25.3.3 可撤销 API Key 与 §25.4 数据模型
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | Sequence[str] | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL,
    last_used_at    TIMESTAMP,
    expires_at      TIMESTAMP,
    is_revoked      INTEGER DEFAULT 0,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_revoked ON api_keys(is_revoked);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS api_keys (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,
    role            TEXT NOT NULL,
    last_used_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,
    is_revoked      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_api_keys_user ON api_keys(user_id);
CREATE INDEX IF NOT EXISTS idx_api_keys_revoked ON api_keys(is_revoked);
"""


def _exec_script(bind: object, script: str) -> None:
    """按分号拆分逐条执行 —— sqlite3 驱动一次只接受一条语句。"""
    from sqlalchemy import text

    for raw in script.split(";"):
        lines = [line for line in raw.splitlines() if not line.strip().startswith("--") and line.strip()]
        if lines:
            newline = chr(10)
            bind.execute(text(newline.join(lines)))


def upgrade() -> None:
    """创建 api_keys 表。"""
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚：删除 api_keys 表。"""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS api_keys"))
