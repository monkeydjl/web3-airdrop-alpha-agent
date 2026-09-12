"""project_skips 表（用户自主「不参与」标记）

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-08

背景：评分/资格 veto 描述的是「这个项目系统判断值不值得参与」，而现实中
用户会基于系统看不见的现实约束（比如「再质押我没那么多资金」）主动放弃
某些项目。这类决定不该污染模型，但也需要有个地方存 —— 否则工作台一直
推荐同一批所谓"该看"的项目，用户要一次次手动跳过。

``UNIQUE(project_id, user_id)`` 是全部约束：同一个用户同一个项目最多一条
记录，重复标记（双击、重试）不产生新行。

刻意**不设 SQL 级外键**（全仓约定）：项目被删/重采时不级联清这条数据 ——
用户历史上点过"不了"是有意义的标记，依赖真实-delete 不是好路由。

数据性质：轻量偏好记录，可随时重建；比 roi 台账轻一致。

Reference:
- app/routers/v1/skip.py
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS project_skips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id  TEXT NOT NULL,
    user_id     TEXT,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, user_id)
);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS project_skips (
    id          SERIAL PRIMARY KEY,
    project_id  TEXT NOT NULL,
    user_id     TEXT,
    created_at  TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(project_id, user_id)
);
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
    """创建 project_skips 表。"""
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚：丢掉用户跳过记录。纯偏好数据、可重建，回滚无资损。"""
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS project_skips"))
