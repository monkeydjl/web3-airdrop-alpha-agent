"""LLM 日预算真实拦截门禁。

`LLM_DAILY_BUDGET_USD` 在 2026-08-24 之前是**装饰性配置**：能填、能通过两个
只读接口查到、但没有任何代码按它拦截。全仓 0 处累计花费 —— 没有累计就无从超限。
这一点比"配置项完全没被读"更难发现：搜一下有 3 处引用，看着像实现了。

这个文件钉住"真的会拦"。它针对的假绿都很具体：

- **成本算成 0 不会被发现**。算错会（数字不对），算成 0 不会 ——
  累计永远是 0，预算永远不超，拦截逻辑写了、测了、跑着，效果等于没写，
  而文档会说它在保护你。所以有三条专门测"未知模型 / 缺 usage / 兜底价配成 0"
  都不会让成本变成 0。
- **测了 `check_budget()` 返回 False 不等于调用真被拦住**。判据必须接进入口：
  有一条断言 `llm_chat()` 在超预算时**一次网络请求都没发出**。
- **只测超预算被拦，分不清"拦对了"和"全都拦了"**。所以有反向断言：
  未超预算时必须放行，预算 0 必须不限额。
- **记账必须真的落库**。内存计数在进程重启时归零，而"花超了"恰好最可能伴随
  重启；多 worker 时每个进程各记一份，每份都没超，合起来是 N 倍预算。
"""

from __future__ import annotations

import sqlite3
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.llm import budget as budget_mod
from app.llm import pricing
from app.llm.client import _RawCompletion, llm_chat

REPO_ROOT = Path(__file__).resolve().parents[2]


def _fresh_db(tmp_path: Path, monkeypatch) -> Path:
    """建一个只含 `llm_spend_daily` 的临时库，并让 `get_connection()` 指向它。

    DDL 手写在这里而不是调 `init_db()`：这个文件测的是预算逻辑，
    建全部 27 张表会让每个用例慢一个数量级。列定义与
    `app/db.py` 的 schema 一致性由 `test_alembic_migration.py` 负责。
    """
    db_path = tmp_path / "budget.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE llm_spend_daily (
            spend_date        TEXT PRIMARY KEY,
            cost_nano_usd     INTEGER NOT NULL DEFAULT 0,
            calls             INTEGER NOT NULL DEFAULT 0,
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()
    monkeypatch.setenv("DB_PATH", str(db_path))
    # settings 是模块级单例，改环境变量不会让它重读 —— 必须直接改字段。
    from app.config import settings

    monkeypatch.setattr(settings, "db_path", str(db_path), raising=True)
    return db_path


def _read_ledger(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(str(db_path))
    try:
        return conn.execute(
            "SELECT spend_date, cost_nano_usd, calls, prompt_tokens, completion_tokens "
            "FROM llm_spend_daily ORDER BY spend_date"
        ).fetchall()
    finally:
        conn.close()


class TestCostIsNeverSilentlyZero:
    """成本估算的三条"静默变成零"路径都必须堵住。

    这是整个预算功能最脆弱的地方：一个永远返回 0 的成本函数会让预算
    完全失效，而所有测试、指标、日志看起来都正常。
    """

    def test_known_model_uses_the_price_table(self) -> None:
        cost, basis = pricing.estimate_cost_usd(
            model="gpt-4o-mini",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=10.0,
        )
        assert basis == pricing.BASIS_TABLE
        assert cost == Decimal("0.15"), f"gpt-4o-mini 输入 1M token 应为 0.15 美元，实际 {cost}"

    def test_model_name_with_date_suffix_still_matches(self) -> None:
        """真实模型名常带日期后缀，必须落到正确档位而不是兜底价。"""
        cost, basis = pricing.estimate_cost_usd(
            model="gpt-4o-mini-2024-07-18",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=10.0,
        )
        assert basis == pricing.BASIS_TABLE
        assert cost == Decimal("0.15")

    def test_longest_prefix_wins(self) -> None:
        """`gpt-4` 是 `gpt-4o` 的前缀，短前缀命中会差 200 倍。"""
        mini, _ = pricing.estimate_cost_usd(
            model="gpt-4o-mini",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=10.0,
        )
        plain, _ = pricing.estimate_cost_usd(
            model="gpt-4",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=10.0,
        )
        assert mini == Decimal("0.15")
        assert plain == Decimal("30.00")
        assert mini < plain, "最长前缀匹配失效 —— gpt-4o-mini 被按 gpt-4 计价了"

    def test_unknown_model_uses_fallback_price_not_zero(self) -> None:
        """价格表查不到 ≠ 免费。

        否则"换一个价格表里没有的模型名"就等于关掉预算 ——
        一个能被随手绕过的预算不是预算。
        """
        cost, basis = pricing.estimate_cost_usd(
            model="some-brand-new-model-v9",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=10.0,
        )
        assert basis == pricing.BASIS_FALLBACK_PRICE
        assert cost == Decimal("10"), f"未知模型应按兜底价 10/1M 计，实际 {cost}"
        assert cost > 0, "未知模型成本为 0 —— 换个模型名就能绕过预算"

    def test_fallback_price_configured_to_zero_still_costs_something(self) -> None:
        """连兜底价都被配成 0 时，仍要有一个非零下限。

        一个"能填成 0 从而关掉整个预算"的配置键，和没有预算是一样的，
        但更坏 —— 因为文档会说预算在生效。
        """
        cost, _ = pricing.estimate_cost_usd(
            model="totally-unknown",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            fallback_price_per_1m_usd=0.0,
        )
        assert cost > 0, "兜底价配成 0 让成本归零 —— 预算被一个配置键关掉了"

    def test_missing_usage_falls_back_to_char_estimate(self) -> None:
        """接口不返回 usage 时按字符估，并标记 estimated。

        OpenAI 兼容接口**不保证**返回 usage（流式、中转、自建都可能省略）。
        缺 usage 就当 0 token = 静默关掉预算。
        """
        prompt_tokens, completion_tokens = pricing.estimate_tokens_from_text(
            prompt_chars=200,
            completion_chars=100,
        )
        assert prompt_tokens == 100
        assert completion_tokens == 50

        cost, basis = pricing.estimate_cost_usd(
            model="gpt-4o-mini",
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            fallback_price_per_1m_usd=10.0,
            tokens_were_estimated=True,
        )
        assert basis == pricing.BASIS_ESTIMATED_TOKENS, (
            "token 是估出来的这件事必须能被区分 —— 它比「用了兜底价」更值得暴露，"
            "因为连输入都不确定，而不只是单价不确定。"
        )
        assert cost > 0

    def test_zero_length_text_still_costs_at_least_one_token(self) -> None:
        """真实发生过的调用不可能是 0 token。"""
        prompt_tokens, completion_tokens = pricing.estimate_tokens_from_text(
            prompt_chars=0,
            completion_chars=0,
        )
        assert prompt_tokens >= 1
        assert completion_tokens >= 1

    def test_every_basis_is_in_the_closed_vocabulary(self) -> None:
        """basis 会进 Prometheus 标签，取值必须闭合。"""
        cases = [
            ("gpt-4o-mini", False),
            ("unknown-model-x", False),
            ("gpt-4o-mini", True),
        ]
        seen = set()
        for model, estimated in cases:
            _, basis = pricing.estimate_cost_usd(
                model=model,
                prompt_tokens=10,
                completion_tokens=10,
                fallback_price_per_1m_usd=10.0,
                tokens_were_estimated=estimated,
            )
            seen.add(basis)
            assert basis in pricing.COST_BASES, f"basis {basis!r} 不在闭合词表里 —— 标签基数会失控"
        assert seen == pricing.COST_BASES, f"三条路径没有覆盖全部 basis 取值，只见到 {sorted(seen)}"


class TestLedgerAccumulatesInTheDatabase:
    """账本必须落库，且并发累加不丢记账。"""

    def test_spend_is_written_and_read_back(self, tmp_path, monkeypatch) -> None:
        db_path = _fresh_db(tmp_path, monkeypatch)
        assert budget_mod.record_spend(cost_usd=Decimal("0.25"), prompt_tokens=100, completion_tokens=50) is True

        spend = budget_mod.get_daily_spend()
        assert spend.cost_usd == Decimal("0.25")
        assert spend.calls == 1
        assert spend.prompt_tokens == 100
        assert spend.completion_tokens == 50
        assert len(_read_ledger(db_path)) == 1

    def test_repeated_spend_accumulates_on_the_same_day(self, tmp_path, monkeypatch) -> None:
        """累加必须是 UPSERT 单语句，先读再写在并发下会丢记账。"""
        _fresh_db(tmp_path, monkeypatch)
        for _ in range(4):
            budget_mod.record_spend(cost_usd=Decimal("0.10"), prompt_tokens=10, completion_tokens=5)

        spend = budget_mod.get_daily_spend()
        assert spend.calls == 4
        assert spend.cost_usd == Decimal("0.4"), f"四次 0.10 应累计 0.40，实际 {spend.cost_usd}"
        assert spend.prompt_tokens == 40
        assert spend.completion_tokens == 20

    def test_amounts_are_compared_in_decimal_domain(self, tmp_path, monkeypatch) -> None:
        """成本是钱，累加与比较必须精确。

        浮点里 0.1+0.2 != 0.3 是真的，而预算判断就是一次 `>=` ——
        累加几万次误差之后 `>=` 的结果不再可信。

        这一条**第一次跑就抓到了真实的错**：第一版账本用 REAL 存美元，
        累加回来是 0.30000000000000004。Python 侧全程 Decimal 没救到它，
        因为累加发生在 SQL 的 UPSERT 里 —— Decimal 管不住那个加号。
        改成纳美元整数存储后才真正精确。
        """
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("0.1"), prompt_tokens=1, completion_tokens=1)
        budget_mod.record_spend(cost_usd=Decimal("0.2"), prompt_tokens=1, completion_tokens=1)
        spend = budget_mod.get_daily_spend()
        assert isinstance(spend.cost_usd, Decimal)
        assert spend.cost_usd == Decimal("0.3"), f"累加应精确得到 0.3，实际 {spend.cost_usd}"

    def test_tiny_amounts_are_not_rounded_to_zero(self, tmp_path, monkeypatch) -> None:
        """很便宜的调用不能被舍成 0 —— 那就回到了「成本静默变成零」。

        一次 100 token 的 gpt-4o-mini 调用约 1.5e-5 美元。
        如果账本单位太粗（比如按分存），这类调用会被记成 0，
        于是"调用很多次但一直很便宜"的场景永远不会触发预算。
        """
        _fresh_db(tmp_path, monkeypatch)
        tiny = Decimal("0.000015")
        assert budget_mod.usd_to_nano(tiny) == 15000, "纳美元换算把小额压掉了"
        budget_mod.record_spend(cost_usd=tiny, prompt_tokens=100, completion_tokens=0)
        spend = budget_mod.get_daily_spend()
        assert spend.cost_usd > 0, "小额调用被舍成 0 —— 预算对高频廉价调用失效"
        assert spend.cost_usd == tiny

    def test_nano_conversion_rounds_up_never_down(self) -> None:
        """换算取上界：宁可高估导致提前熔断，不要低估导致不熔断。"""
        assert budget_mod.usd_to_nano(Decimal("0.0000000001")) == 1, "低于 1 纳美元的花费被抹成免费"
        assert budget_mod.usd_to_nano(Decimal("0")) == 0
        assert budget_mod.usd_to_nano(Decimal("-5")) == 0
        assert budget_mod.nano_to_usd(1_500_000_000) == Decimal("1.5")

    def test_record_failure_returns_false_and_does_not_raise(self, tmp_path, monkeypatch) -> None:
        """记账失败绝不向上抛：这一步在 LLM 已经成功返回之后。

        为了记账失败而丢弃一个已经付过钱的结果是纯亏损。
        但也不能静默 —— 返回 False 让调用方去递增失败指标。
        """
        _fresh_db(tmp_path, monkeypatch)

        def boom(*args, **kwargs):
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(budget_mod.LLMSpendRepository, "add", boom, raising=True)
        assert budget_mod.record_spend(cost_usd=Decimal("1"), prompt_tokens=1, completion_tokens=1) is False


class TestBudgetDecision:
    """判定逻辑本身，含两个方向。"""

    def test_under_budget_is_allowed(self, tmp_path, monkeypatch) -> None:
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("0.2"), prompt_tokens=1, completion_tokens=1)
        decision = budget_mod.check_budget(budget_usd=1.0)
        assert decision.allowed is True
        assert decision.reason == budget_mod.REASON_OK
        assert decision.remaining_usd == Decimal("0.8")

    def test_over_budget_is_refused(self, tmp_path, monkeypatch) -> None:
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("1.5"), prompt_tokens=1, completion_tokens=1)
        decision = budget_mod.check_budget(budget_usd=1.0)
        assert decision.allowed is False
        assert decision.reason == budget_mod.REASON_BUDGET_EXCEEDED

    def test_exactly_at_budget_is_refused(self, tmp_path, monkeypatch) -> None:
        """边界取 `>=`：花到正好等于预算就该停。

        取 `>` 的话，预算 1.0 会在花到 1.0 时继续放行，
        实际上限变成 1.0 + 单次成本，而配置写的是 1.0。
        """
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("1.0"), prompt_tokens=1, completion_tokens=1)
        decision = budget_mod.check_budget(budget_usd=1.0)
        assert decision.allowed is False

    @pytest.mark.parametrize("budget", [0.0, -1.0])
    def test_zero_or_negative_budget_means_unlimited(self, budget, tmp_path, monkeypatch) -> None:
        """0 = 不限额，而不是"全部拒绝"。

        0 是"没配"的自然表达。把它解释成"一律禁止 LLM"会让一个漏填的配置
        静默关掉功能，现象是"LLM 好像没生效" —— 一个很难查的现象。
        """
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("999"), prompt_tokens=1, completion_tokens=1)
        decision = budget_mod.check_budget(budget_usd=budget)
        assert decision.allowed is True
        assert decision.reason == budget_mod.REASON_DISABLED

    def test_ledger_failure_fails_closed(self, tmp_path, monkeypatch) -> None:
        """读不到账本时拒绝，而不是放行。

        fail-open 的代价：一次 DB 抖动 = 当天预算不生效，且**没有任何现象**，
        账单第二天才知道。fail-closed 的代价：降级回规则引擎 —— 而规则引擎
        是本项目永远可用的默认路径（ADR-001）。两边代价差好几个数量级。
        """
        _fresh_db(tmp_path, monkeypatch)

        def boom(*args, **kwargs):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(budget_mod, "get_daily_spend", boom, raising=True)
        decision = budget_mod.check_budget(budget_usd=1.0)
        assert decision.allowed is False
        assert decision.reason == budget_mod.REASON_LEDGER_UNAVAILABLE

    def test_every_reason_is_in_the_closed_vocabulary(self) -> None:
        for reason in (
            budget_mod.REASON_OK,
            budget_mod.REASON_DISABLED,
            budget_mod.REASON_BUDGET_EXCEEDED,
            budget_mod.REASON_LEDGER_UNAVAILABLE,
        ):
            assert reason in budget_mod.BUDGET_REASONS


class TestLlmChatActuallyRefuses:
    """判据必须接进入口：`check_budget()` 返回 False 不等于调用被拦住。

    这一类是本文件的核心。一个正确的 `check_budget()` 加上一个忘了调用它的
    `llm_chat()`，会让上面所有断言全绿而预算毫无作用 —— 这正是
    `m7_bom_check_removed` / `a8_middleware_bypass` 同一类失效。
    """

    @staticmethod
    def _settings(budget: float) -> MagicMock:
        mock = MagicMock()
        mock.llm_providers = [
            {
                "base_url": "https://api1.com/v1",
                "api_key": "key1",
                "name": "provider-1",
                "models": ["gpt-4o-mini"],
            }
        ]
        mock.llm_temperature = 0.3
        mock.llm_max_tokens = 512
        mock.llm_daily_budget_usd = budget
        mock.llm_fallback_price_per_1m_usd = 10.0
        return mock

    @pytest.mark.asyncio
    async def test_over_budget_sends_zero_network_requests(self, tmp_path, monkeypatch) -> None:
        """超预算时**一个字节都不发出去**，这才是"拦截"而不是"事后记账"。"""
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("5"), prompt_tokens=1, completion_tokens=1)
        monkeypatch.setattr("app.llm.client.settings", self._settings(1.0))

        calls: list[str] = []

        async def spy_try_single(provider, model, **kwargs):
            calls.append(model)
            return _RawCompletion(text="should never happen", raw_usage=None)

        monkeypatch.setattr("app.llm.client._try_single", spy_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert result.text is None
        assert result.refused_reason == budget_mod.REASON_BUDGET_EXCEEDED
        assert calls == [], f"超预算却仍然发出了 {len(calls)} 次请求 —— 拦截没有接进调用路径"

    @pytest.mark.asyncio
    async def test_under_budget_still_calls_through(self, tmp_path, monkeypatch) -> None:
        """反向断言：只测"超了被拦"分不清"拦对了"和"全都拦了"。"""
        _fresh_db(tmp_path, monkeypatch)
        monkeypatch.setattr("app.llm.client.settings", self._settings(1.0))

        calls: list[str] = []

        async def spy_try_single(provider, model, **kwargs):
            calls.append(model)
            return _RawCompletion(
                text="real answer",
                raw_usage={"prompt_tokens": 100, "completion_tokens": 50},
            )

        monkeypatch.setattr("app.llm.client._try_single", spy_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "real answer"
        assert result.refused_reason is None
        assert calls == ["gpt-4o-mini"]

    @pytest.mark.asyncio
    async def test_successful_call_is_recorded_in_the_ledger(self, tmp_path, monkeypatch) -> None:
        """成功调用必须留下账 —— 不记账的花费永远不计入预算。"""
        db_path = _fresh_db(tmp_path, monkeypatch)
        monkeypatch.setattr("app.llm.client.settings", self._settings(1.0))

        async def ok_try_single(provider, model, **kwargs):
            return _RawCompletion(
                text="answer",
                raw_usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
            )

        monkeypatch.setattr("app.llm.client._try_single", ok_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert result.usage is not None
        assert result.usage.cost_usd == Decimal("0.15")
        assert result.usage.estimated is False

        rows = _read_ledger(db_path)
        assert len(rows) == 1
        assert rows[0][2] == 1, "调用次数没有记上"
        assert rows[0][1] == 150_000_000, f"账本纳美元金额 {rows[0][1]} 与估算成本 0.15 美元不符"

    @pytest.mark.asyncio
    async def test_provider_without_usage_field_still_records_cost(self, tmp_path, monkeypatch) -> None:
        """接口省略 usage 时仍要记出非零成本，否则等于免费。"""
        db_path = _fresh_db(tmp_path, monkeypatch)
        monkeypatch.setattr("app.llm.client.settings", self._settings(1.0))

        async def no_usage(provider, model, **kwargs):
            return _RawCompletion(text="x" * 400, raw_usage=None)

        monkeypatch.setattr("app.llm.client._try_single", no_usage)

        result = await llm_chat(messages=[{"role": "user", "content": "y" * 200}])
        assert result.usage is not None
        assert result.usage.estimated is True
        assert result.usage.basis == pricing.BASIS_ESTIMATED_TOKENS
        assert result.usage.cost_usd > 0

        rows = _read_ledger(db_path)
        assert rows[0][1] > 0, "缺 usage 的调用被记成 0 成本 —— 预算被静默关掉"

    @pytest.mark.asyncio
    async def test_spending_across_calls_eventually_trips_the_budget(self, tmp_path, monkeypatch) -> None:
        """端到端：连续调用把账本推过预算线，后续调用被拒。

        这条同时验证了那个**诚实的边界**：拦截在调用前、成本在调用后才知道，
        所以最后一次被放行的调用一定会把当日花费推过预算线。
        超出量最多是单次调用成本 —— 这不是 bug，是"事前拦截 + 事后计费"
        这个结构的必然结果。
        """
        _fresh_db(tmp_path, monkeypatch)
        # 预算 0.5 美元；每次调用 1M 输入 token 的 gpt-4o-mini = 0.15 美元
        monkeypatch.setattr("app.llm.client.settings", self._settings(0.5))

        async def ok_try_single(provider, model, **kwargs):
            return _RawCompletion(
                text="answer",
                raw_usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
            )

        monkeypatch.setattr("app.llm.client._try_single", ok_try_single)

        outcomes = []
        for _ in range(6):
            r = await llm_chat(messages=[{"role": "user", "content": "hi"}])
            outcomes.append(r.ok)

        # 0.15 × 4 = 0.60 ≥ 0.5，所以第 4 次之后开始拒绝：前 4 次成功
        assert outcomes[:4] == [True, True, True, True], f"预算 0.5 应允许前 4 次调用，实际 {outcomes}"
        assert outcomes[4:] == [False, False], f"累计超预算后应停止调用，实际 {outcomes}"

        spend = budget_mod.get_daily_spend()
        assert spend.cost_usd >= Decimal("0.5"), "花费没有累计上去"
        # 软上限的诚实边界：超出量不超过一次调用的成本
        assert spend.cost_usd <= Decimal("0.5") + Decimal("0.15")


class TestMetricsActuallyIncrement:
    """指标必须真的动起来 —— 注册了但从不递增比名字写错更坏。

    这一类存在的理由是一个真实的历史事实：`airdrop_llm_requests_total` /
    `airdrop_llm_errors_total` / `airdrop_llm_duration_seconds` 从注册那天起
    到 2026-08-24 之前**从未被递增过一次**。它们注册了、暴露在 `/metrics` 里、
    被 OBSERVABILITY.md 记录、还有一条 `HighLLMErrorRate` 告警建立在其上。

    **一个存在但永不增长的指标，在面板上是平直的 0 线、在告警里是永不触发，
    两者看起来都像"系统很健康"。** 这比指标名写错更坏 —— 名字写错时查询查不到
    数据，还有机会被发现。

    所以断言不能只查"指标是否注册"（那正是当年通过了的检查），
    必须**跑一次真实调用路径，再比对递增量**。
    """

    @staticmethod
    def _value(name: str, **labels: str) -> float:
        from prometheus_client import REGISTRY

        got = REGISTRY.get_sample_value(name, labels or None)
        return 0.0 if got is None else float(got)

    @pytest.mark.asyncio
    async def test_successful_call_moves_cost_token_and_attempt_metrics(self, tmp_path, monkeypatch) -> None:
        _fresh_db(tmp_path, monkeypatch)
        monkeypatch.setattr("app.llm.client.settings", TestLlmChatActuallyRefuses._settings(10.0))

        async def ok(provider, model, **kwargs):
            return _RawCompletion(
                text="answer",
                raw_usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
            )

        monkeypatch.setattr("app.llm.client._try_single", ok)

        before = {
            "requests": self._value("airdrop_llm_requests_total", model="gpt-4o-mini"),
            "cost": self._value("airdrop_llm_cost_usd_total", model="gpt-4o-mini", basis=pricing.BASIS_TABLE),
            "tokens": self._value("airdrop_llm_tokens_total", model="gpt-4o-mini", direction="prompt"),
        }

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert result.ok is True

        after = {
            "requests": self._value("airdrop_llm_requests_total", model="gpt-4o-mini"),
            "cost": self._value("airdrop_llm_cost_usd_total", model="gpt-4o-mini", basis=pricing.BASIS_TABLE),
            "tokens": self._value("airdrop_llm_tokens_total", model="gpt-4o-mini", direction="prompt"),
        }

        assert after["requests"] == before["requests"] + 1, (
            "airdrop_llm_requests_total 没有递增 —— 这个指标又回到了「注册了但永不增长」的状态，"
            "而 HighLLMErrorRate 告警的分母正是它。"
        )
        assert after["cost"] > before["cost"], "airdrop_llm_cost_usd_total 没有递增 —— 成本面板会是一条平直的 0 线。"
        assert after["tokens"] == before["tokens"] + 1_000_000, "airdrop_llm_tokens_total 没有按真实 token 数递增。"

    @pytest.mark.asyncio
    async def test_budget_block_is_visible_in_metrics(self, tmp_path, monkeypatch) -> None:
        """拦住了但看不见，等于运维无法知道为什么解读质量突然变差。"""
        _fresh_db(tmp_path, monkeypatch)
        budget_mod.record_spend(cost_usd=Decimal("5"), prompt_tokens=1, completion_tokens=1)
        monkeypatch.setattr("app.llm.client.settings", TestLlmChatActuallyRefuses._settings(1.0))

        async def never(provider, model, **kwargs):
            raise AssertionError("超预算时不应该发出请求")

        monkeypatch.setattr("app.llm.client._try_single", never)

        before = self._value(
            "airdrop_llm_budget_blocked_total",
            reason=budget_mod.REASON_BUDGET_EXCEEDED,
        )
        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert result.ok is False
        after = self._value(
            "airdrop_llm_budget_blocked_total",
            reason=budget_mod.REASON_BUDGET_EXCEEDED,
        )
        assert after == before + 1, (
            "预算拦了一次调用，但 airdrop_llm_budget_blocked_total 没动 —— LLMBudgetExhausted 告警将永不触发。"
        )

    @pytest.mark.asyncio
    async def test_budget_gauges_reflect_current_state(self, tmp_path, monkeypatch) -> None:
        """两个 gauge 必须反映真实状态，否则"还剩多少余量"无从判断。"""
        _fresh_db(tmp_path, monkeypatch)
        monkeypatch.setattr("app.llm.client.settings", TestLlmChatActuallyRefuses._settings(3.0))

        async def ok(provider, model, **kwargs):
            return _RawCompletion(
                text="answer",
                raw_usage={"prompt_tokens": 1_000_000, "completion_tokens": 0},
            )

        monkeypatch.setattr("app.llm.client._try_single", ok)
        await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert self._value("airdrop_llm_budget_usd") == 3.0, "预算 gauge 与配置不一致"
        # 第二次调用时 gauge 才会带上第一次的花费（拦截发生在调用前）
        await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert self._value("airdrop_llm_spend_today_usd") > 0, (
            "airdrop_llm_spend_today_usd 一直是 0 —— 只有上限没有用量，看不出还剩多少余量。"
        )

    def test_label_vocabularies_are_closed_sets(self) -> None:
        """标签值必须来自闭合词表，禁止运行时拼字符串。

        `basis` 与 `reason` 都进 Prometheus 标签。如果它们能是任意字符串，
        标签基数会随模型数/错误文案增长而爆炸 —— 这是把 Prometheus 打挂的
        经典方式，而且不会立刻表现出来。
        """
        from app import metrics as metrics_mod

        expected_bases = {
            pricing.BASIS_TABLE,
            pricing.BASIS_FALLBACK_PRICE,
            pricing.BASIS_ESTIMATED_TOKENS,
        }
        expected_reasons = {
            budget_mod.REASON_OK,
            budget_mod.REASON_DISABLED,
            budget_mod.REASON_BUDGET_EXCEEDED,
            budget_mod.REASON_LEDGER_UNAVAILABLE,
        }
        expected_directions = {"prompt", "completion"}

        assert set(pricing.COST_BASES) == expected_bases
        assert set(budget_mod.BUDGET_REASONS) == expected_reasons
        assert set(metrics_mod.LLM_TOKEN_DIRECTIONS) == expected_directions


class TestDocsNoLongerClaimItIsFake:
    """三份文档都必须已经改口。

    把未实现写成已实现，会让人在风险评估里数进一个不存在的控制；
    把**已实现**写成未实现，会让人重做一遍，或者放弃一个可用的控制。
    这条钉后者 —— 而且这里是三份文档，都曾明确写着"只展示不拦截"。
    """

    @staticmethod
    def _text(rel: str) -> str:
        path = REPO_ROOT / rel
        assert path.is_file(), f"{rel} 不存在 —— 被测对象没了。"
        text = path.read_text(encoding="utf-8")
        assert len(text) > 5000, f"{rel} 只有 {len(text)} 字符，疑似被截断 —— 解析器已失效。"
        return text

    def test_security_no_longer_says_display_only(self) -> None:
        text = self._text("docs/SECURITY.md")
        for lie in ("只展示不拦截", "没有任何拦截"):
            assert lie not in text, f"SECURITY.md 仍写着「{lie}」，但预算现在真的会拦。"

    def test_operations_no_longer_says_budget_is_fake(self) -> None:
        text = self._text("docs/OPERATIONS.md")
        assert "LLM 成本预算真实拦截 | ❌" not in text, "OPERATIONS.md §11 仍把预算拦截列为未实现。"
        assert "LLM token / 成本指标 | ❌" not in text, "OPERATIONS.md §11 仍说没有 token / 成本指标。"

    def test_env_example_no_longer_warns_it_does_nothing(self) -> None:
        text = self._text(".env.example")
        assert "没有任何按它拦截调用的逻辑" not in text, ".env.example 仍写着预算不拦截。"
        assert "LLM_FALLBACK_PRICE_PER_1M_USD" in text, ".env.example 缺少新增的兜底单价配置键。"

    def test_observability_documents_the_new_metrics(self) -> None:
        """新指标必须写进 OBSERVABILITY.md。

        **没写进文档的指标等于不存在** —— 没人会去查一个他不知道的指标名。
        """
        text = self._text("docs/OBSERVABILITY.md")
        for metric in (
            "airdrop_llm_cost_usd_total",
            "airdrop_llm_tokens_total",
            "airdrop_llm_budget_blocked_total",
            "airdrop_llm_spend_record_failures_total",
            "airdrop_llm_budget_usd",
            "airdrop_llm_spend_today_usd",
        ):
            assert metric in text, f"OBSERVABILITY.md 没有记录新指标 `{metric}`。"

    def test_the_ghost_metric_list_no_longer_claims_cost_metrics_are_fake(self) -> None:
        """§3.3「这些指标不存在」清单里必须拿掉已经实现的成本指标。

        把一个真实存在的指标列进"不存在"清单，会让人放弃使用一个可用的指标 ——
        清单本身就成了新的谎言。
        """
        text = self._text("docs/OBSERVABILITY.md")
        start = text.index("### 3.3")
        ghost_block = text[start : text.index("### 3.4", start)]
        for metric in ("airdrop_llm_cost_usd_total", "airdrop_llm_tokens_total"):
            assert metric not in ghost_block, (
                f"§3.3 仍把 `{metric}` 列为「代码里一个都没有」，但它现在是真实注册的指标。"
            )
