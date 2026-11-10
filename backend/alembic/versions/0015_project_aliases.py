"""dedup_keys as project alias store

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-09

`dedup_keys` was created in the baseline but never written by the main
pipeline. It becomes the project-identity alias store (see
``app/identity.py``): manual aliases outrank backfill/auto ones, and a
missing alias falls back to the legacy ``uuid5("name::sector")`` so existing
project IDs never drift. ``source`` NULL marks pre-existing rows, which the
resolver deliberately ignores.

No SQL-level foreign keys (repo-wide convention).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | Sequence[str] | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _dedup_columns(bind: object) -> set[str]:
    """Handle a fresh baseline built from current db.py and upgraded old databases."""
    from sqlalchemy import inspect

    return {column["name"] for column in inspect(bind).get_columns("dedup_keys")}


def upgrade() -> None:
    """Add alias metadata columns and the source index."""
    from sqlalchemy import text

    bind = op.get_bind()
    ts_type = "TIMESTAMPTZ" if bind.dialect.name == "postgresql" else "TIMESTAMP"
    existing = _dedup_columns(bind)
    for column, definition in (
        ("source", "TEXT"),
        ("confidence", "REAL"),
        ("notes", "TEXT"),
        ("updated_at", ts_type),
    ):
        if column not in existing:
            bind.execute(text(f"ALTER TABLE dedup_keys ADD COLUMN {column} {definition}"))
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_dedup_source ON dedup_keys(source)"))


def downgrade() -> None:
    """Drop the alias metadata; project IDs stay resolvable via the legacy uuid5 fallback."""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS idx_dedup_source"))
    existing = _dedup_columns(bind)
    for column in ("updated_at", "notes", "confidence", "source"):
        if column in existing:
            bind.execute(text(f"ALTER TABLE dedup_keys DROP COLUMN {column}"))
