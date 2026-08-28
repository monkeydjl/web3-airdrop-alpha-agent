"""Agent 路径的预算拦截必须与"调用失败"区分开（实测口径）。

## 背景

此前 `BaseAgent.llm_enhance()` 用的是 `llm_chat_simple()` —— 它丢掉
`LLMResult.refused_reason`，于是「预算拦下（预期降级）」「账本不可读
（fail-closed 事故）」「接口全挂」在 agent 路径上**长得一模一样**：
都返回 None，日志要么没有、要么只有一条 `llm.failed`。

2026-08-25 改为调用完整的 `llm_chat()` 并按拒绝原因分流：

| 场景 | 日志事件 | 级别 |
|---|---|---|
| 预算耗尽 / 被预算规则拦下 | `llm.budget_refused` | info（预期行为） |
| 账本读不出来 → fail-closed | `llm.ledger_fail_closed` | **error**（对应 critical 告警） |
| 正常成功 | `llm.success` | info |
| 抛异常（网络/接口） | `llm.failed` | error |

这些测试断言的就是上面这张表 —— 它们是「分类没被改回一锅烩」的门禁。

## 为什么用 capture_logs 而不是 caplog

本项目的日志走 **structlog 自己的输出管道**（configure_logging 写文件 /
stdout），不经过 stdlib logging 的 handler —— pytest 的 caplog 一个事件
都收不到（第一次跑就证明了这点：断言拿到空串，而 stderr 上明明有
渲染好的那行）。`structlog.testing.capture_logs()` 才是本仓库的正确工具。
"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, patch

import pytest
from structlog.testing import capture_logs

from app.agents.base import AgentContext, BaseAgent, PipelineState, RawProject
from app.db import init_db
from app.llm.budget import REASON_BUDGET_EXCEEDED, REASON_LEDGER_UNAVAILABLE
from app.llm.client import LLMResult


@pytest.fixture
def db_conn():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    yield conn
    conn.close()


class _RefusalTestAgent(BaseAgent):
    async def run(self, state: PipelineState) -> PipelineState:
        return state


def _state(discovery_score: float = 0.9) -> PipelineState:
    project = RawProject(
        id=f"budget-refusal-{discovery_score}",
        name="Budget Refusal Probe",
        sector="L2",
        stage="testnet",
        source="test",
    )
    project.discovery_score = discovery_score
    return PipelineState(
        project=project,
        context=AgentContext(run_id="budget-refusal-run", enable_llm=True),
    )


def _result(**kwargs) -> LLMResult:
    base: dict = {"text": None, "provider_used": "p1", "model_used": "m1"}
    base.update(kwargs)
    return LLMResult(**base)


async def _run(result: LLMResult, agent: BaseAgent | None = None):
    """跑一次 llm_enhance，同时捕获 structlog 事件。返回 (返回值, 事件列表)。"""
    # _resolve_prompt_version 里对 None 连接查表会抛异常，但它自带
    # except → 返回 None，不影响本次要测的分流路径。
    agent = agent or _RefusalTestAgent("TestAgent")
    state = _state()
    with (
        patch("app.db.get_connection", return_value=None),
        patch("app.llm.client.llm_chat", new_callable=AsyncMock, return_value=result),
        capture_logs() as events,
    ):
        outcome = await agent.llm_enhance(state, "probe prompt")
    return outcome, events


def _names(events) -> set[str]:
    return {e["event"] for e in events}


class _MethodRecorder:
    """替身记录器：按方法名记下调用了哪个级别。

    capture_logs 的条目里没有 level 字段（那要靠生产端的渲染处理器补上），
    所以「fail-closed 必须 error 级」这条只能在这里验证：
    直接看代码调用的是 .error 还是 .info。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def bind(self, **kw):  # 兼容 structlog 接口
        return self

    def info(self, event: str, **kw) -> None:
        self.calls.append(("info", event, kw))

    def error(self, event: str, **kw) -> None:
        self.calls.append(("error", event, kw))

    def warning(self, event: str, **kw) -> None:
        self.calls.append(("warning", event, kw))


class TestBudgetRefusalIsDistinctFromFailure:
    @pytest.mark.asyncio
    async def test_budget_exceeded_logs_budget_refused_not_failed(self, db_conn):
        """预算耗尽：info 级 `llm.budget_refused`，绝不能落成 `llm.failed`。"""
        outcome, events = await _run(_result(refused_reason=REASON_BUDGET_EXCEEDED))

        assert outcome is None
        names = _names(events)
        assert "llm.budget_refused" in names
        entry = next(e for e in events if e["event"] == "llm.budget_refused")
        assert entry["reason"] == REASON_BUDGET_EXCEEDED
        assert "llm.failed" not in names, "预算拦截被当成了失败记录 —— 这正是要修的那个混淆。"

    @pytest.mark.asyncio
    async def test_ledger_unavailable_is_error_level(self, db_conn):
        """账本不可读 → fail-closed 是**事故**：error 级专属事件。"""
        agent = _RefusalTestAgent("TestAgent")
        recorder = _MethodRecorder()
        agent.logger = recorder

        outcome = None
        # logger 换成替身之后，structlog 事件全部落到 recorder ——
        # 这正是断言来源；capture_logs 这里是空的，别从它取。
        agent_llm = agent.logger
        assert agent_llm is recorder

        with (
            patch("app.db.get_connection", return_value=None),
            patch(
                "app.llm.client.llm_chat",
                new_callable=AsyncMock,
                return_value=_result(refused_reason=REASON_LEDGER_UNAVAILABLE),
            ),
        ):
            outcome = await agent.llm_enhance(_state(), "probe prompt")

        assert outcome is None
        all_events = [(level, event) for level, event, _kw in recorder.calls]
        assert ("error", "llm.ledger_fail_closed") in all_events
        info_events = [event for level, event, _kw in recorder.calls if level == "info"]
        assert "llm.failed" not in {e for _l, e in all_events}
        assert "llm.ledger_fail_closed" not in info_events

    @pytest.mark.asyncio
    async def test_plain_exception_still_logs_llm_failed(self, db_conn):
        """反向锚点：真异常仍走 llm.failed —— 分流不能把失败也吞掉。"""
        agent = _RefusalTestAgent("TestAgent")
        state = _state()
        with (
            patch("app.db.get_connection", return_value=db_conn),
            patch(
                "app.llm.client.llm_chat",
                new_callable=AsyncMock,
                side_effect=RuntimeError("connection exploded"),
            ),
            capture_logs() as events,
        ):
            outcome = await agent.llm_enhance(state, "probe prompt")

        assert outcome is None
        names = _names(events)
        assert "llm.failed" in names
        failed = next(e for e in events if e["event"] == "llm.failed")
        assert "connection exploded" in str(failed.get("error", ""))
        assert "llm.budget_refused" not in names
        assert "llm.ledger_fail_closed" not in names

    @pytest.mark.asyncio
    async def test_success_path_unchanged(self, db_conn):
        """成功路径照旧返回文本并记 llm.success。"""
        outcome, events = await _run(_result(text="enhanced text"))

        assert outcome == "enhanced text"
        assert "llm.success" in _names(events)

    @pytest.mark.asyncio
    async def test_no_response_path_unchanged(self, db_conn):
        """text 为 None 且无拒绝原因 → llm.no_response（原行为保留）。"""
        outcome, events = await _run(_result())

        assert outcome is None
        assert "llm.no_response" in _names(events)
