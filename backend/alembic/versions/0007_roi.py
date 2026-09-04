"""roi_entries / roi_outcomes tables (F3 收益台账)

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-31

收益台账（ACTION_LOOP_DESIGN.md §4）的投入/产出两张表。

- ``roi_entries`` = 投入（gas / infra / time / other）。时间投入用 ``hours``，
  金钱投入用 ``amount_usd``，两者可只填其一 —— 早期参与的绝大成本是时间，
  没有小时数这个维度台账会严重低估投入。
- ``roi_outcomes`` = 产出（token_launched / airdrop_received / airdrop_missed /
  campaign_ended）。``source`` 区分 ``manual``（人工录入）与 ``backtest``
  （历史回测导出），校准时两类样本**分开统计**（§4.3），不混算。

诚实边界（§4.2）：``amount_usd`` 以人工录入为准，MVP 不做链上自动取价 ——
代币价格源是另一个工程，不塞进本期。``tx_hash`` 只作凭证存档，不自动验证。
把它当成"能自动对账的字段"会给人虚假的确权感。

身份边界：user_id 来自 token（``get_current_user``），**不接受请求体自报**
—— 与 0006 参与流水同源的教训（2026-08-30 审核 P1-1）。

刻意**不设 SQL 级外键**（全仓约定）：投入产出按 (user_id, project_id) 聚合，
project 删除由路由层显式处理，不靠数据库级约束兜底。

Reference:
- app/routers/v1/roi.py
- app/calibration.py（source 分桶）
- docs/ACTION_LOOP_DESIGN.md §4.2 / §4.3
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS roi_entries (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    amount_usd  REAL,
    hours       REAL,
    note        TEXT,
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roi_entries_user_project
    ON roi_entries(user_id, project_id);

CREATE TABLE IF NOT EXISTS roi_outcomes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    event       TEXT NOT NULL,
    amount_usd  REAL,
    tokens      REAL,
    tx_hash     TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roi_outcomes_user_project
    ON roi_outcomes(user_id, project_id);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS roi_entries (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    kind        TEXT NOT NULL,
    amount_usd  DOUBLE PRECISION,
    hours       DOUBLE PRECISION,
    note        TEXT,
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roi_entries_user_project
    ON roi_entries(user_id, project_id);

CREATE TABLE IF NOT EXISTS roi_outcomes (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    project_id  TEXT NOT NULL,
    event       TEXT NOT NULL,
    amount_usd  DOUBLE PRECISION,
    tokens      DOUBLE PRECISION,
    tx_hash     TEXT,
    source      TEXT NOT NULL DEFAULT 'manual',
    recorded_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_roi_outcomes_user_project
    ON roi_outcomes(user_id, project_id);
"""


def _exec_script(bind: object, script: str) -> None:
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
    """创建收益台账两张表。"""
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚两张收益台账表。

    回滚丢掉全部投入产出记录 —— 这是人工录入的账本，删掉无法从任何其它
    数据源重建（回测样本 source=backtest 可重跑脚本再生成，live 的不行）。
    回滚前必须确认，需要留存请先导出。
    """
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS roi_outcomes"))
    bind.execute(text("DROP TABLE IF EXISTS roi_entries"))
