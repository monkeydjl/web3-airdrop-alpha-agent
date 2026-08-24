"""LLM 日预算账本：累计每日花费，并在超预算时拒绝新调用。

`LLM_DAILY_BUDGET_USD` 在此之前是一个**装饰性配置** —— 能填、能通过接口查到、
但没有任何代码按它拦截调用。全仓 0 处累计花费，因此也无从超限。
这个模块补上缺的那一半。

## 为什么账本必须落库，不能只放内存

内存计数器在**进程重启时归零**。而"花超了"恰好是最可能伴随重启的场景
（有人看到账单异常、重启服务、计数清零、继续花）。
更普通的情况：uvicorn 多 worker、或者容器滚动更新 —— 每个进程各自记一份，
每份都没超，合起来是 N 倍预算。**按进程计的预算不是预算。**

## 失败方向的选择：拦不住 vs 拦太多

读账本会失败（DB 锁、磁盘满、表不存在）。两种选择：

- **fail-open**（读不到就放行）：一次 DB 抖动就等于当天预算不生效，
  而且**没有任何现象** —— 日志里一条 warning，账单第二天才知道。
- **fail-closed**（读不到就拒绝）：LLM 停用，降级回规则引擎。

这里选 **fail-closed**。理由不是"安全优先"这种口号，而是这个系统的具体形状：
**LLM 是可选增强，规则引擎是永远可用的默认路径**（ADR-001）。
拒绝一次 LLM 调用的代价是"这个项目的解读少了一段润色"，
放行一次超预算调用的代价是真实账单。两边代价差好几个数量级。

如果哪天 LLM 变成不可降级的关键路径，这个判断要重新做 —— 所以理由写在这里，
而不是只写"fail closed"。

## 一个诚实的边界：预算是软上限

拦截发生在**调用之前**，而一次调用的成本只有**调用之后**才知道。
所以最后一次被放行的调用一定会把当日花费推过预算线，超出量最多是
单次调用的成本（`LLM_MAX_TOKENS` 决定了它的上界）。

这不是 bug，是"事前拦截 + 事后计费"这个结构的必然结果。
把它写清楚，因为一个声称"绝不超过 1 美元"的预算在账单上显示 1.003 美元时，
第一反应会是"拦截没生效"。

## 时区

按 **UTC 日期** 分桶，与 `docs/OPERATIONS.md` 里所有 cron 的口径一致
（调度器 `timezone=UTC`）。用本地时区会让"今天"的边界随部署机器漂移。
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import structlog

from app.db import dict_from_row

logger = structlog.get_logger(__name__)


def today_utc() -> str:
    """当日 UTC 日期（`YYYY-MM-DD`）。"""
    return _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")


# 金额在 DB 里以**纳美元整数**存储。
#
# 第一版用 REAL 存美元，测试立刻抓到：0.1 + 0.2 累加回来是
# 0.30000000000000004。在 Python 侧用 Decimal 只保证"读出来是 Decimal"，
# **管不住 SQL 里的那个加号** —— 而累加恰恰是在 SQL 的 UPSERT 里做的。
#
# 选纳（1e-9）而不是微（1e-6）：一次便宜调用约 1.5e-5 美元，
# 微美元下是 15，纳美元下是 15000。任何把小额舍成 0 的路径都会回到
# "成本静默变成零"—— 那是这整个功能最需要避免的失效形态。
_NANO = Decimal("1000000000")


def usd_to_nano(cost_usd: Decimal) -> int:
    """美元 Decimal → 纳美元整数。

    向上取整（`ceil`）而不是四舍五入：**宁可高估，不要低估。**
    高估的后果是提前熔断 + 一条明确日志；低估的后果是账单。
    """
    if cost_usd <= 0:
        return 0
    nano = cost_usd * _NANO
    as_int = int(nano)
    return as_int if Decimal(as_int) == nano else as_int + 1


def nano_to_usd(cost_nano_usd: int) -> Decimal:
    """纳美元整数 → 美元 Decimal（精确，无浮点参与）。"""
    return Decimal(int(cost_nano_usd)) / _NANO


@dataclass(frozen=True)
class DailySpend:
    """某一天的累计用量。"""

    spend_date: str
    cost_usd: Decimal
    calls: int
    prompt_tokens: int
    completion_tokens: int


@dataclass(frozen=True)
class BudgetDecision:
    """预算判定结果。

    `allowed=False` 时 `reason` 必填，且会原样进日志与指标标签，
    所以取值是闭合的（见 `REASON_*`）。
    """

    allowed: bool
    reason: str
    budget_usd: Decimal
    spent_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return self.budget_usd - self.spent_usd


# 闭合的拒绝原因词表。进 Prometheus 标签，禁止拼接动态字符串。
REASON_OK = "ok"
REASON_DISABLED = "budget_disabled"  # 预算 <= 0，视为不限额
REASON_BUDGET_EXCEEDED = "budget_exceeded"  # 当日累计已达/超过预算
REASON_LEDGER_UNAVAILABLE = "ledger_unavailable"  # 账本读不出来 → fail closed
BUDGET_REASONS: frozenset[str] = frozenset(
    {REASON_OK, REASON_DISABLED, REASON_BUDGET_EXCEEDED, REASON_LEDGER_UNAVAILABLE}
)


class LLMSpendRepository:
    """`llm_spend_daily` 表数据访问。

    只有两个操作：读某天的累计、往某天累加。
    累加用 UPSERT 在**一条语句**里完成 —— 先 SELECT 再 UPDATE 的写法在
    并发下会丢记账（两个请求都读到 1.0，都写成 1.5，实际应是 2.0）。
    路由处理器现在跑在线程池里，这是真实存在的并发。

    SQL 里一律写 SQLite 占位符 `?`：`DbConnection` 会在 Postgres 上改写成
    `%s`。绕过它自己判断方言，就等于多一处需要同步维护的方言分支。
    """

    def __init__(self, conn: Any) -> None:
        self.conn = conn

    def get(self, spend_date: str) -> DailySpend:
        row = self.conn.execute(
            "SELECT spend_date, cost_nano_usd, calls, prompt_tokens, completion_tokens "
            "FROM llm_spend_daily WHERE spend_date = ?",
            (spend_date,),
        ).fetchone()
        if row is None:
            return DailySpend(
                spend_date=spend_date,
                cost_usd=Decimal("0"),
                calls=0,
                prompt_tokens=0,
                completion_tokens=0,
            )
        return _row_to_spend(row)

    def add(
        self,
        *,
        spend_date: str,
        cost_usd: Decimal,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """把一次调用的用量累加到当天。"""
        self.conn.execute(
            """
            INSERT INTO llm_spend_daily
                (spend_date, cost_nano_usd, calls, prompt_tokens, completion_tokens, updated_at)
            VALUES (?, ?, 1, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (spend_date) DO UPDATE SET
                cost_nano_usd     = cost_nano_usd + excluded.cost_nano_usd,
                calls             = calls + 1,
                prompt_tokens     = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens,
                updated_at        = CURRENT_TIMESTAMP
            """,
            (spend_date, usd_to_nano(cost_usd), int(prompt_tokens), int(completion_tokens)),
        )
        self.conn.commit()

    def list_recent(self, *, limit: int = 30) -> list[DailySpend]:
        rows = self.conn.execute(
            "SELECT spend_date, cost_nano_usd, calls, prompt_tokens, completion_tokens "
            "FROM llm_spend_daily ORDER BY spend_date DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_spend(row) for row in rows]


def _row_to_spend(row: Any) -> DailySpend:
    """DB 行 → `DailySpend`（纳美元整数 → Decimal 美元）。"""
    data = dict_from_row(row)
    return DailySpend(
        spend_date=str(data["spend_date"]),
        cost_usd=nano_to_usd(int(data["cost_nano_usd"] or 0)),
        calls=int(data["calls"] or 0),
        prompt_tokens=int(data["prompt_tokens"] or 0),
        completion_tokens=int(data["completion_tokens"] or 0),
    )


def _open_repo() -> tuple[Any, LLMSpendRepository]:
    from app.db import get_connection

    conn = get_connection()
    return conn, LLMSpendRepository(conn)


def get_daily_spend(spend_date: str | None = None) -> DailySpend:
    """读取某天累计（默认今天）。DB 不可用时抛异常，由调用方决定方向。"""
    day = spend_date or today_utc()
    conn, repo = _open_repo()
    try:
        return repo.get(day)
    finally:
        conn.close()


def check_budget(*, budget_usd: float) -> BudgetDecision:
    """调用前的预算判定。

    `budget_usd <= 0` 视为**不限额**（而不是"全部拒绝"）：0 是"没配"的
    自然表达，把它解释成"一律禁止 LLM"会让一个漏填的配置直接关掉功能，
    而现象是"LLM 好像没生效"—— 一个很难查的现象。
    真要关 LLM 有明确的开关（`ENABLE_LLM_ENHANCEMENT`）。
    """
    budget = Decimal(str(max(float(budget_usd), 0.0)))
    if budget <= 0:
        return BudgetDecision(allowed=True, reason=REASON_DISABLED, budget_usd=budget, spent_usd=Decimal("0"))

    try:
        spend = get_daily_spend()
    except Exception as exc:
        # fail closed —— 理由见模块 docstring：降级回规则引擎的代价远小于账单。
        logger.error("llm.budget.ledger_unavailable", error=str(exc)[:200])
        return BudgetDecision(
            allowed=False,
            reason=REASON_LEDGER_UNAVAILABLE,
            budget_usd=budget,
            spent_usd=Decimal("0"),
        )

    if spend.cost_usd >= budget:
        logger.warning(
            "llm.budget.exceeded",
            spend_date=spend.spend_date,
            spent_usd=float(spend.cost_usd),
            budget_usd=float(budget),
            calls_today=spend.calls,
        )
        return BudgetDecision(
            allowed=False,
            reason=REASON_BUDGET_EXCEEDED,
            budget_usd=budget,
            spent_usd=spend.cost_usd,
        )

    return BudgetDecision(allowed=True, reason=REASON_OK, budget_usd=budget, spent_usd=spend.cost_usd)


def record_spend(*, cost_usd: Decimal, prompt_tokens: int, completion_tokens: int) -> bool:
    """把一次调用记进当天账本。返回是否记账成功。

    **记账失败绝不向上抛**：这一步发生在 LLM 已经成功返回之后，
    为了记账失败而丢弃一个已经付过钱的结果是纯亏损。
    但也不能静默 —— 记账失败意味着**这次花费永远不会被计入预算**，
    累积起来就是预算失效。所以打 error 日志 + 递增专门的指标，
    让"少记了多少次"可被观测。
    """
    try:
        conn, repo = _open_repo()
        try:
            repo.add(
                spend_date=today_utc(),
                cost_usd=cost_usd,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
            return True
        finally:
            conn.close()
    except Exception as exc:
        logger.error(
            "llm.budget.record_failed",
            error=str(exc)[:200],
            cost_usd=float(cost_usd),
        )
        return False
