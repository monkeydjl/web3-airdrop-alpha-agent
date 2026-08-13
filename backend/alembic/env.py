"""Alembic 迁移环境。

复用 app.config / app.db 的双后端连接逻辑，确保 alembic 与 init_db() 指向同一库：
- 设置 DATABASE_URL（postgresql://…）→ PostgreSQL（SQLAlchemy 用 postgresql+psycopg 驱动）
- 未设置 → SQLite（settings.db_path，默认 data/airdrop.db）

迁移目标库由 settings 统一控制（与运行时一致）：
- SQLite：DB_PATH 环境变量（如 DB_PATH=./migrate_smoke.db）
- PostgreSQL：DATABASE_URL 环境变量

target_metadata = None：本项目迁移以原生 SQL（复用 init_db / op.execute）为主，
不走 SQLAlchemy autogenerate。
"""

from __future__ import annotations

from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# 导入应用配置，复用与运行时一致的连接判定（prepend_sys_path = . 使 app 可导入）
from app.config import settings
from app.db import is_postgres

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 解析数据库 URL（与 init_db / get_connection 完全一致）──────────
if is_postgres():
    # psycopg3 驱动：SQLAlchemy 需要 postgresql+psycopg:// 前缀
    raw = settings.database_url or ""
    raw = raw.replace("postgresql+psycopg://", "postgresql://")
    raw = raw.replace("postgresql+psycopg2://", "postgresql://")
    if raw.startswith("postgresql://"):
        raw = "postgresql+psycopg://" + raw[len("postgresql://") :]
    elif raw.startswith("postgres://"):
        raw = "postgresql+psycopg://" + raw[len("postgres://") :]
    db_url = raw
else:
    db_path = Path(settings.db_path)
    # SQLite 文件需要父目录存在（SQLAlchemy 不会自动创建目录）
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_url = f"sqlite:///{db_path}"

config.set_main_option("sqlalchemy.url", db_url)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = None

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
