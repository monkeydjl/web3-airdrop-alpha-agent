"""Add default-list hiding storage to projects.

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-08

`hidden_reason` / `hidden_at` record why the launch review hid a project from
default lists (confirmed launched token with no post-launch airdrop path). Rows
are never deleted: history, feedback and participation plans stay attached, and
the same review clears both columns once a path reappears.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | Sequence[str] | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = ("hidden_reason", "hidden_at")


def _project_columns(bind: object) -> set[str]:
    """Handle a fresh baseline built from current db.py and upgraded old databases."""
    from sqlalchemy import inspect

    return {column["name"] for column in inspect(bind).get_columns("projects")}


def upgrade() -> None:
    """Add the nullable hiding columns to projects when absent."""
    from sqlalchemy import text

    bind = op.get_bind()
    existing = _project_columns(bind)
    ts_type = "TIMESTAMPTZ" if bind.dialect.name == "postgresql" else "TIMESTAMP"
    if "hidden_reason" not in existing:
        bind.execute(text("ALTER TABLE projects ADD COLUMN hidden_reason TEXT"))
    if "hidden_at" not in existing:
        bind.execute(text(f"ALTER TABLE projects ADD COLUMN hidden_at {ts_type}"))


def downgrade() -> None:
    """Remove hiding data; hidden projects simply reappear in default lists."""
    from sqlalchemy import text

    bind = op.get_bind()
    # db.py's rolling baseline may already contain the columns in fresh test DBs.
    existing = _project_columns(bind)
    for column in _COLUMNS:
        if column in existing:
            bind.execute(text(f"ALTER TABLE projects DROP COLUMN {column}"))
