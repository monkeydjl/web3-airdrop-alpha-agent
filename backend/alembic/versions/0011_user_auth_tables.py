"""V3 用户认证表（users, sessions, blacklisted_jti）

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-19

Reference:
- ADR-008-user-system.md §3 核心数据模型
- ENGINEERING_ROADMAP.md §25.4 数据模型（V3 新增表）
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer',
    is_active       INTEGER DEFAULT 1,
    preferences     TEXT,
    last_login_at   TIMESTAMP,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    refresh_token_hash  TEXT NOT NULL UNIQUE,
    ip                  TEXT,
    user_agent          TEXT,
    expires_at          TIMESTAMP NOT NULL,
    revoked             INTEGER DEFAULT 0,
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS blacklisted_jti (
    jti             TEXT PRIMARY KEY,
    expires_at      TIMESTAMP NOT NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_blacklisted_expires ON blacklisted_jti(expires_at);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    display_name    TEXT,
    role            TEXT NOT NULL DEFAULT 'viewer',
    is_active       INTEGER DEFAULT 1,
    preferences     TEXT,
    last_login_at   TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL,
    refresh_token_hash  TEXT NOT NULL UNIQUE,
    ip                  TEXT,
    user_agent          TEXT,
    expires_at          TIMESTAMPTZ NOT NULL,
    revoked             INTEGER DEFAULT 0,
    created_at          TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS blacklisted_jti (
    jti             TEXT PRIMARY KEY,
    expires_at      TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
CREATE INDEX IF NOT EXISTS idx_blacklisted_expires ON blacklisted_jti(expires_at);
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
    """创建 users, sessions, blacklisted_jti 表。"""
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚：删除 users, sessions, blacklisted_jti 表。"""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS sessions"))
    bind.execute(text("DROP TABLE IF EXISTS blacklisted_jti"))
    bind.execute(text("DROP TABLE IF EXISTS users"))
