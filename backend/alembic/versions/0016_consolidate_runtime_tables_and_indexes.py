"""Consolidate runtime tables, leader_election, and unique dedup indexes

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-20

Brings all previously out-of-band / request-time tables and idempotency indexes
under Alembic management so `alembic upgrade head` produces the exact same
schema as `init_db()` on both SQLite and PostgreSQL:
- leader_election (+ idx_leader_election_expires)
- harvest_records (+ idx_harvest_records_claimed)
- faucet_claims (+ idx_faucet_claims_user)
- gas_alert_rules (+ idx_gas_alert_rules_chain)
- team_studio_operators
- team_studio_tasks (+ idx_team_studio_tasks_operator)
- project_signals.external_id + ux_project_signals_identity
- ux_raw_projects_source_dedup
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | Sequence[str] | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_columns(bind: object, table_name: str) -> set[str]:
    from sqlalchemy import inspect

    insp = inspect(bind)
    if not insp.has_table(table_name):
        return set()
    return {column["name"] for column in insp.get_columns(table_name)}


def upgrade() -> None:
    """Create consolidated operational tables and unique idempotency indexes."""
    from sqlalchemy import text

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    ts_type = "TIMESTAMPTZ" if is_pg else "TIMESTAMP"
    real_type = "DOUBLE PRECISION" if is_pg else "REAL"
    created_int_type = "BIGINT" if is_pg else "INTEGER"

    statements = [
        f"""
        CREATE TABLE IF NOT EXISTS leader_election (
            resource_id       TEXT PRIMARY KEY,
            leader_id         TEXT NOT NULL,
            lease_expires_at  {ts_type} NOT NULL,
            acquired_at       {ts_type} NOT NULL,
            version           INTEGER NOT NULL DEFAULT 1
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_leader_election_expires ON leader_election(lease_expires_at)",
        f"""
        CREATE TABLE IF NOT EXISTS harvest_records (
            id                TEXT PRIMARY KEY,
            project_name      TEXT NOT NULL,
            token_symbol      TEXT NOT NULL,
            amount_claimed    {real_type} NOT NULL,
            ath_price_usd     {real_type} NOT NULL,
            current_price_usd {real_type} NOT NULL,
            gas_spent_usd     {real_type} NOT NULL DEFAULT 0,
            claimed_at        TEXT,
            notes             TEXT,
            is_default        INTEGER NOT NULL DEFAULT 0,
            created_at        {ts_type} DEFAULT CURRENT_TIMESTAMP
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_harvest_records_claimed ON harvest_records(claimed_at DESC)",
        f"""
        CREATE TABLE IF NOT EXISTS faucet_claims (
            claim_id       TEXT PRIMARY KEY,
            user_id        TEXT NOT NULL,
            faucet_id      TEXT NOT NULL,
            claimed_at     {ts_type} NOT NULL,
            cooldown_hours INTEGER DEFAULT 24
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_faucet_claims_user ON faucet_claims(user_id, faucet_id)",
        f"""
        CREATE TABLE IF NOT EXISTS gas_alert_rules (
            rule_id        TEXT PRIMARY KEY,
            chain          TEXT NOT NULL,
            condition      TEXT NOT NULL,
            threshold_gwei {real_type} NOT NULL,
            label          TEXT NOT NULL,
            enabled        INTEGER NOT NULL DEFAULT 1,
            created_at     {ts_type}
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_gas_alert_rules_chain ON gas_alert_rules(chain, enabled)",
        f"""
        CREATE TABLE IF NOT EXISTS team_studio_operators (
            operator_id        TEXT PRIMARY KEY,
            name               TEXT NOT NULL,
            role               TEXT NOT NULL DEFAULT 'Operator',
            assigned_wallets   INTEGER NOT NULL DEFAULT 10,
            assigned_projects  TEXT NOT NULL DEFAULT '[]',
            today_completed_tx INTEGER NOT NULL DEFAULT 0,
            today_target_tx    INTEGER NOT NULL DEFAULT 0,
            completion_rate    {real_type} NOT NULL DEFAULT 0.0,
            gas_spent_usd      {real_type} NOT NULL DEFAULT 0.0,
            status             TEXT NOT NULL DEFAULT 'idle',
            ip_proxy_isolated  INTEGER,
            last_active        TEXT,
            updated_at         {ts_type} DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS team_studio_tasks (
            task_id             TEXT PRIMARY KEY,
            title               TEXT NOT NULL,
            project             TEXT NOT NULL,
            operator_id         TEXT NOT NULL,
            target_wallet_count INTEGER NOT NULL DEFAULT 1,
            status              TEXT NOT NULL DEFAULT 'pending',
            priority            TEXT NOT NULL DEFAULT 'medium',
            deadline            TEXT,
            created_at          {created_int_type} NOT NULL
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_team_studio_tasks_operator ON team_studio_tasks(operator_id, status)",
    ]
    for stmt in statements:
        bind.execute(text(stmt))

    signal_cols = _table_columns(bind, "project_signals")
    if signal_cols and "external_id" not in signal_cols:
        bind.execute(text("ALTER TABLE project_signals ADD COLUMN external_id TEXT"))

    bind.execute(
        text("CREATE UNIQUE INDEX IF NOT EXISTS ux_raw_projects_source_dedup ON raw_projects(source_id, dedup_key)")
    )
    bind.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_project_signals_identity "
            "ON project_signals(dedup_key, signal_type, signal_source, external_id)"
        )
    )


def downgrade() -> None:
    """Drop consolidated tables, unique indexes, and project_signals.external_id."""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP INDEX IF EXISTS ux_project_signals_identity"))
    bind.execute(text("DROP INDEX IF EXISTS ux_raw_projects_source_dedup"))

    signal_cols = _table_columns(bind, "project_signals")
    if "external_id" in signal_cols:
        bind.execute(text("ALTER TABLE project_signals DROP COLUMN external_id"))

    for table in (
        "team_studio_tasks",
        "team_studio_operators",
        "gas_alert_rules",
        "faucet_claims",
        "harvest_records",
        "leader_election",
    ):
        bind.execute(text(f"DROP TABLE IF EXISTS {table}"))
