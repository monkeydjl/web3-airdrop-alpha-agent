"""token_registry table + projects.unhidden_by_user_at

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-08

``token_registry`` caches CoinGecko's full coin list so the launch review and the
listed-token gate can confirm launches for projects whose own source gives no
token evidence (RootData rows with an empty token field). It is rebuilt
wholesale on refresh and holds no history; an empty table simply disables the
check.

``unhidden_by_user_at`` records a manual "show this again" from the UI. The
launch review never re-hides a project carrying it.

No SQL-level foreign keys (repo-wide convention).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | Sequence[str] | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project_columns(bind: object) -> set[str]:
    """Handle a fresh baseline built from current db.py and upgraded old databases."""
    from sqlalchemy import inspect

    return {column["name"] for column in inspect(bind).get_columns("projects")}


def upgrade() -> None:
    """Create the registry cache and the manual-unhide marker."""
    from sqlalchemy import text

    bind = op.get_bind()
    ts_type = "TIMESTAMPTZ" if bind.dialect.name == "postgresql" else "TIMESTAMP"
    bind.execute(
        text(
            "CREATE TABLE IF NOT EXISTS token_registry ("
            " coin_id TEXT PRIMARY KEY,"
            " symbol TEXT NOT NULL,"
            " name TEXT NOT NULL,"
            " name_key TEXT NOT NULL,"
            f" fetched_at {ts_type} NOT NULL)"
        )
    )
    bind.execute(text("CREATE INDEX IF NOT EXISTS idx_token_registry_name_key ON token_registry(name_key)"))
    if "unhidden_by_user_at" not in _project_columns(bind):
        bind.execute(text(f"ALTER TABLE projects ADD COLUMN unhidden_by_user_at {ts_type}"))


def downgrade() -> None:
    """Drop the cache (refetchable) and the marker (manual restores become auto-reviewable again)."""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS token_registry"))
    if "unhidden_by_user_at" in _project_columns(bind):
        bind.execute(text("ALTER TABLE projects DROP COLUMN unhidden_by_user_at"))
