"""llm_spend_daily table (LLM daily budget ledger)

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24

补上 `LLM_DAILY_BUDGET_USD` 缺的那一半。

这个配置项此前是**装饰性**的：能填、能通过 `/api/v1/llm/status` 与
`/api/v1/settings/config` 查到、但没有任何代码按它拦截调用。
全仓 0 处累计花费 —— **没有累计就无从超限**。
这比"配置项完全没被读"更容易骗过检查：搜一下发现有 3 处引用，看着像实现了。

## 为什么需要一张表

内存计数器在进程重启时归零，而"花超了"恰好是最可能伴随重启的场景
（有人看到账单异常 → 重启服务 → 计数清零 → 继续花）。
更普通的情况：多 worker 或容器滚动更新时每个进程各记一份，
每份都没超，合起来是 N 倍预算。**按进程计的预算不是预算。**

## 为什么金额列是整数

累加在 SQL 里做（UPSERT 单语句），而 REAL 累加会漂 —— 实测 0.1+0.2 存回来是
0.30000000000000004。在 Python 侧用 Decimal 只能保证"读出来是 Decimal"，
**管不住 SQL 里的那个加号**。

所以金额以**纳美元（1e-9 USD）整数**存储，SQL 加法完全精确。
选纳而不是微：一次很便宜的调用约 1.5e-5 美元，微美元单位下会被舍成 15，
纳美元下是 15000 —— 而任何舍入到 0 的路径都会回到"成本静默变成零"。
int64 上限对应约 9.2e9 美元，溢出不是一个现实问题。

## 为什么 spend_date 做主键

累加必须用 UPSERT 在一条语句里完成。先 SELECT 再 UPDATE 的写法在并发下
会丢记账（两个请求都读到 1.0，都写成 1.5，实际应是 2.0），
而路由处理器现在跑在线程池里，这是真实存在的并发。
`ON CONFLICT (spend_date)` 需要该列上有唯一约束，主键最直接。

Reference:
- app/llm/budget.py（账本与判定）
- app/llm/pricing.py（单次成本估算）
- docs/SECURITY.md §10.4 Model Safety
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SQLITE_SQL = """
CREATE TABLE IF NOT EXISTS llm_spend_daily (
    spend_date        TEXT PRIMARY KEY,
    cost_nano_usd     INTEGER NOT NULL DEFAULT 0,
    calls             INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

_PG_SQL = """
CREATE TABLE IF NOT EXISTS llm_spend_daily (
    spend_date        TEXT PRIMARY KEY,
    cost_nano_usd     BIGINT NOT NULL DEFAULT 0,
    calls             INTEGER NOT NULL DEFAULT 0,
    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    updated_at        TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
);
"""


def upgrade() -> None:
    """创建 llm_spend_daily 表。"""
    from sqlalchemy import text

    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    bind.execute(text((_PG_SQL if is_pg else _SQLITE_SQL).strip()))


def downgrade() -> None:
    """回滚 llm_spend_daily 表。

    回滚会**丢掉全部历史花费记录**。这是有意的：这张表是运行时账本，
    不是业务数据，重建后从当天 0 开始累计即可。
    需要留存的话，回滚前自行 `.dump` 一份。
    """
    from sqlalchemy import text

    bind = op.get_bind()
    bind.execute(text("DROP TABLE IF EXISTS llm_spend_daily"))
