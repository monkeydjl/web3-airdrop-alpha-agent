"""Add ADR-015 eligibility veto storage to projects.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-01

The veto records why a weighted FARM score was downgraded by a deterministic
eligibility rule. It preserves score semantics and is nullable: a later successful
rescore with no veto clears stale prior policy state.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_veto_column(bind: object) -> bool:
    """Handle a fresh baseline built from current db.py and upgraded old databases."""
    from sqlalchemy import inspect

    return "veto" in {column["name"] for column in inspect(bind).get_columns("projects")}


def upgrade() -> None:
    """Add the nullable eligibility-veto reason to projects when absent."""
    from sqlalchemy import text

    bind = op.get_bind()
    if not _has_veto_column(bind):
        bind.execute(text("ALTER TABLE projects ADD COLUMN veto TEXT"))


def downgrade() -> None:
    """Remove eligibility-veto data when reverting ADR-015 where it was added."""
    from sqlalchemy import text

    bind = op.get_bind()
    # db.py's rolling baseline may already contain the column in fresh test DBs.
    # Alembic's historical path still performs a best-effort schema rollback.
    if _has_veto_column(bind):
        bind.execute(text("ALTER TABLE projects DROP COLUMN veto"))
