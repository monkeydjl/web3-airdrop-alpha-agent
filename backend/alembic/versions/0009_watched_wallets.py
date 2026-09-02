"""watched_wallets table (F4 领取监控)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-02

领取监控（ACTION_LOOP_DESIGN.md §5）的自有地址登记表。

``address`` 一律**小写存储**且 UNIQUE。归一必须在写入侧与匹配侧同时做 ——
只做一侧的话 UNIQUE 形同虚设（`0xAbC` 与 `0xabc` 各占一行），而 Alchemy
webhook payload 实际返回 EIP-55 校验和格式的混合大小写。这与 competition
分组的教训是同一类：同一实体的多种写法必须在唯一入口归一，否则各处静默失配。

``active`` 是软开关：保留登记但停止匹配（临时静音），与删除区分。Alchemy
控制台侧的地址清单在 MVP 是手工维护的（§5.2 非目标），所以本地 active=0
时 webhook 仍会收到事件，只是不再产生 airdrop_candidate。

方言差异：SQLite 用 INTEGER DEFAULT 1，PG 用 BOOLEAN DEFAULT TRUE。PG 有原生
布尔、读出来就是 True/False，两侧类型不同因此转换统一放在读取侧。

安全边界（§5.4）：钱包地址是资金隐私。``/api/v1/watched-wallets`` 整前缀
管理员锁，且通知内容只含 label + 地址前 10 位 —— 截断做在事件构造侧而非
API 响应层，因为推送目的地（Telegram/Discord）不受本系统控制。

刻意**不设 SQL 级外键**（全仓约定）：本表不引用其它表。

Reference:
- app/routers/v1/watched_wallets.py
- app/routers/v1/webhook.py（地址匹配）
- docs/ACTION_LOOP_DESIGN.md §5.3 / §5.4
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS watched_wallets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    address    TEXT NOT NULL UNIQUE,
    label      TEXT NOT NULL,
    chain      TEXT NOT NULL DEFAULT 'ethereum',
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_watched_wallets_active
    ON watched_wallets(active, address);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS watched_wallets (
    id         SERIAL PRIMARY KEY,
    address    TEXT NOT NULL UNIQUE,
    label      TEXT NOT NULL,
    chain      TEXT NOT NULL DEFAULT 'ethereum',
    active     BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_watched_wallets_active
    ON watched_wallets(active, address);
"""


def _exec_script(bind: object, script: str) -> None:
    """按分号拆分逐条执行 —— sqlite3 驱动一次只接受一条语句。

    同 0005/0006/0007：含 CREATE INDEX 就必须拆。注释行先剥掉，
    避免空语句/注释残留被当成语句执行。
    """
    from sqlalchemy import text

    for raw in script.split(";"):
        lines = [line for line in raw.splitlines() if not line.strip().startswith("--") and line.strip()]
        if lines:
            newline = chr(10)
            bind.execute(text(newline.join(lines)))


def upgrade() -> None:
    """创建自有地址登记表。"""
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    _exec_script(bind, (_PG_SQL if is_pg else _SQLITE_SQL).strip())


def downgrade() -> None:
    """回滚自有地址登记表。

    回滚丢掉全部登记地址。这份清单是人工录入的，但**可以重建** —— 地址本身
    在用户自己的钱包里，label 是自定义备注。相比 roi 台账（人工录入且无法从
    任何数据源重建）风险低一档，仍建议回滚前导出留存。

    注意 Alchemy 控制台侧的地址清单不受本次回滚影响（MVP 手工维护），
    回滚后 webhook 仍会收到那些地址的事件，只是本地匹配不到、不再产生
    airdrop_candidate。
    """
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS watched_wallets"))
