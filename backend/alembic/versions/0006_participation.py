"""participation_plans / participation_tasks tables (F2 参与流水)

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-31

参与流水（ACTION_LOOP_DESIGN.md §3）的服务端状态机。

- plan = 「我在参与这个项目」，(user_id, project_id) 唯一 —— 同一用户对
  同一项目最多一个 plan，重复创建返回 409 而不是静默加倍。
- task = 具体动作，`ref` 列保存建议生成器（participation_tasks.py）的
  task_id：seed_from_generated 重复导入时按 (plan_id, ref) 去重，
  不产生同一建议的两行。
- 刻意**不设 SQL 级外键**（全仓约定，opportunity 的 PG schema 同规）：
  级联删除由路由层显式先删 task 再删 plan（任务不是独立资产，但没有
  数据库级约束兜底 —— 这与仓内所有其它表一致）。

身份边界：user_id 来自 token（`get_current_user`），**不接受请求体自报**
—— 2026-08-30 审核 P1-1 的同款教训，匿名入口 + 客户端身份 = 任何人都能
读写别人的流水。

Reference:
- app/routers/v1/participation.py
- docs/ACTION_LOOP_DESIGN.md §3.3
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS participation_plans (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    note        TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP,
    UNIQUE (user_id, project_id)
);

CREATE TABLE IF NOT EXISTS participation_tasks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id      INTEGER NOT NULL,
    ref          TEXT,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'other',
    status       TEXT NOT NULL DEFAULT 'todo',
    url          TEXT,
    due_at       TIMESTAMP,
    note         TEXT,
    completed_at TIMESTAMP,
    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_participation_tasks_plan
    ON participation_tasks(plan_id, status);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS participation_plans (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'active',
    note        TEXT,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMPTZ,
    UNIQUE (user_id, project_id)
);

CREATE TABLE IF NOT EXISTS participation_tasks (
    id           SERIAL PRIMARY KEY,
    plan_id      INTEGER NOT NULL,
    ref          TEXT,
    title        TEXT NOT NULL,
    kind         TEXT NOT NULL DEFAULT 'other',
    status       TEXT NOT NULL DEFAULT 'todo',
    url          TEXT,
    due_at       TIMESTAMPTZ,
    note         TEXT,
    completed_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_participation_tasks_plan
    ON participation_tasks(plan_id, status);
"""


def _exec_script(bind: Any, script: str) -> None:
    """按分号拆分逐条执行 —— sqlite3 驱动一次只接受一条语句。

    0004 的模板是单条 DDL 没踩到这个坑；0005 起含 CREATE INDEX 就必须拆。
    注释行先剥掉，避免空语句/注释残留被当成语句执行。
    """
    from sqlalchemy import text

    for raw in script.split(";"):
        lines = [line for line in raw.splitlines() if not line.strip().startswith("--") and line.strip()]
        if lines:
            newline = chr(10)
            bind.execute(text(newline.join(lines)))


def upgrade() -> None:
    """创建参与流水两张表。

    `text` 不在这里 import —— DDL 全部经 `_exec_script` 执行，它自己拿 `text`。
    """
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚两张参与流水表。

    回滚丢掉全部参与记录 —— 参与流水是用户操作数据，不是可再生成的
    运行时账本。回滚前必须确认，需要留存请自行导出。
    """
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS participation_tasks"))
    bind.execute(text("DROP TABLE IF EXISTS participation_plans"))
