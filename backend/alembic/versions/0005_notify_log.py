"""notify_log table (outbound decision-push log)

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-31

决策推送（ACTION_LOOP_DESIGN.md §2）的出站日志表。

- `(event_key, channel)` 唯一：同一事件对同一通道天然去重。评估器可以
  随便重复产出事件（cron 重跑、进程重启），入库走 UPSERT 忽略，发送侧
  只处理 `pending` 的行 —— 「至少一次评估、至多一次发送」由这一条
  唯一约束保证，不靠调用方自觉。
- `attempts` / `last_error`：发送重试 ≤3 次后置 `failed` 不再自动重发。
  通知是尽力而为，不是事务承诺 —— 失败的行留在表里供 /notify/log 排查。

Reference:
- app/notify/（评估器与发送器）
- docs/ACTION_LOOP_DESIGN.md §2.5
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS notify_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT NOT NULL,
    event_key   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at     TIMESTAMP,
    UNIQUE (event_key, channel)
);
CREATE INDEX IF NOT EXISTS idx_notify_log_status
    ON notify_log(status, created_at);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS notify_log (
    id          SERIAL PRIMARY KEY,
    event_type  TEXT NOT NULL,
    event_key   TEXT NOT NULL,
    channel     TEXT NOT NULL,
    title       TEXT NOT NULL,
    body        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'pending',
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_error  TEXT,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    sent_at     TIMESTAMPTZ,
    UNIQUE (event_key, channel)
);
CREATE INDEX IF NOT EXISTS idx_notify_log_status
    ON notify_log(status, created_at);
"""


from typing import Any

def _exec_script(bind: Any, script: str) -> None:
    """按分号拆分逐条执行 —— sqlite3 驱动一次只接受一条语句。

    0004 的模板是单条 DDL 没踩到这个坑；0005 起含 CREATE INDEX 就必须拆。
    注释行先剥掉，避免空语句/注释残留被当成语句执行。
    """
    from sqlalchemy import text

    for raw in script.split(";"):
        lines = [
            line
            for line in raw.splitlines()
            if not line.strip().startswith("--") and line.strip()
        ]
        if lines:
            newline = chr(10)
            bind.execute(text(newline.join(lines)))


def upgrade() -> None:
    """创建 notify_log 表。"""
    from sqlalchemy import text

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚 notify_log 表。

    回滚丢掉出站历史。这是有意的：日志是运行时排障数据，不是业务数据；
    需要留存的话回滚前自行导出一份。
    """
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS notify_log"))
