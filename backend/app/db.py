"""Database Access Layer.

MVP: SQLite (WAL 模式)
V2+: PostgreSQL (通过 DATABASE_URL 切换)

参考：
- CONVENTIONS.md §13 数据库访问模式
- DATABASE_DDL.md 完整 DDL 定义
"""

import sqlite3
from pathlib import Path
from typing import Any

from app.config import settings


def get_connection() -> sqlite3.Connection:
    """获取 SQLite 数据库连接。

    使用 WAL 模式提升并发读写性能。
    每次调用返回新连接，调用方负责关闭。

    Returns:
        sqlite3.Connection: 配置好的数据库连接

    Example:
        conn = get_connection()
        try:
            conn.execute("SELECT * FROM projects")
        finally:
            conn.close()
    """
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection | None = None) -> None:
    """幂等建表。

    读取 DATABASE_DDL.md 中的 DDL 语句创建所有表。
    安全重复执行（IF NOT EXISTS）。

    Args:
        conn: 可选的数据库连接。不提供时创建新连接。

    Example:
        init_db()  # 使用默认连接
        init_db(conn)  # 使用指定连接
    """
    if conn is None:
        conn = get_connection()
        should_close = True
    else:
        should_close = False

    try:
        # 核心表 DDL（完整 DDL 见 docs/DATABASE_DDL.md）
        # MVP 阶段仅创建核心表，V2 表通过 Alembic 迁移添加
        conn.executescript("""
            -- 项目主表
            CREATE TABLE IF NOT EXISTS projects (
                id              TEXT PRIMARY KEY,
                name            TEXT NOT NULL,
                url             TEXT,
                sector          TEXT,
                stage           TEXT,
                score           INTEGER,
                label           TEXT,
                recommendation  TEXT,
                confidence      REAL,
                weight_version  TEXT,
                reason          TEXT,
                narrative_json  TEXT,
                team_json       TEXT,
                risk_json       TEXT,
                tokenomics_json TEXT,
                raw_signals     TEXT,
                meta            TEXT,
                source          TEXT,
                raw_signals_hash TEXT,
                fetched_at      TIMESTAMP,
                created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 运行日志表
            CREATE TABLE IF NOT EXISTS logs (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id      TEXT NOT NULL,
                project_id  TEXT,
                agent_name  TEXT,
                input       TEXT,
                output      TEXT,
                error       TEXT,
                duration_ms INTEGER,
                timestamp   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 索引
            CREATE INDEX IF NOT EXISTS idx_projects_score ON projects(score);
            CREATE INDEX IF NOT EXISTS idx_projects_label ON projects(label);
            CREATE INDEX IF NOT EXISTS idx_projects_sector ON projects(sector);
            CREATE INDEX IF NOT EXISTS idx_projects_updated ON projects(updated_at);
            CREATE INDEX IF NOT EXISTS idx_logs_run ON logs(run_id);
            CREATE INDEX IF NOT EXISTS idx_logs_project ON logs(project_id);
        """)
        conn.commit()
    finally:
        if should_close:
            conn.close()


def dict_from_row(row: sqlite3.Row) -> dict[str, Any]:
    """将 sqlite3.Row 转换为普通 dict。

    Args:
        row: 数据库行对象

    Returns:
        包含所有字段的字典
    """
    return dict(row) if row else {}
