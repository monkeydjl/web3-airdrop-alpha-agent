"""Tests for Team Studio Manager — 诚实口径契约 + SQLite 持久化.

2026-09-23 审计后，此服务不再内置虚构操作员（Alice/Bob/Charlie 及编造的
完成率/Gas 数据）。新团队从空态开始；隔离评级在无真实数据源时输出 None。

持久化（2026-09-23）：操作员/任务已从模块级内存列表迁移到 SQLite
（team_studio_operators / team_studio_tasks），重启保留。测试通过直连
`:memory:` 连接做隔离——每条用例拿到的是独立空库，天然不泄漏状态
（此前内存列表靠 fixture 双向 clear，漏一处就跨文件污染）。
"""

import sqlite3

import pytest

from app.services.team_studio_manager import (
    assign_task_to_operator,
    get_team_studio_dashboard,
    register_or_update_operator,
)


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_dashboard_starts_empty_honestly(db_conn: sqlite3.Connection) -> None:
    """空态必须如实为 0 操作员/0 任务，禁止内置演示数据."""
    data = get_team_studio_dashboard(db_conn)
    assert data["summary"]["active_operators_count"] == 0
    assert data["summary"]["total_managed_wallets"] == 0
    assert data["operators"] == []
    assert data["assigned_tasks"] == []
    # 隔离评级无真实数据源时输出 None，不编「100% 合规」
    assert data["summary"]["sybil_isolation_rating"] is None
    # 已落库：persist_note 必须如实说明持久化状态，且不再有「重启即失」字样
    assert "SQLite" in data["persist_note"]
    assert "重启即失" not in data["persist_note"]


def test_register_then_assign_flow(db_conn: sqlite3.Connection) -> None:
    reg = register_or_update_operator(
        operator_id="op_test",
        name="Tester",
        role="Operator",
        assigned_wallets=5,
        conn=db_conn,
    )
    assert reg["action"] == "created"
    assert reg["operator"]["today_completed_tx"] == 0

    res = assign_task_to_operator(
        title="Test batch task",
        project="Monad",
        operator_id="op_test",
        target_wallet_count=5,
        conn=db_conn,
    )
    assert res["success"] is True
    assert res["task"]["status"] == "pending"

    data = get_team_studio_dashboard(db_conn)
    assert data["summary"]["active_operators_count"] == 1
    assert len(data["assigned_tasks"]) == 1
    assert data["operators"][0]["operator_id"] == "op_test"


def test_persistence_across_connections(tmp_path) -> None:
    """持久化契约：写入后关闭连接、再用全新连接打开同一库 —— 数据必须存活.

    用真实文件库模拟重启（``:memory:`` 不跨连接共享，测不了这件事）：
    若实现退回内存列表，重开连接后读不到已注册的操作员，此用例即红。
    """
    import sqlite3 as _sqlite3

    db_file = tmp_path / "studio_persist.db"
    writer = _sqlite3.connect(str(db_file))
    register_or_update_operator(
        operator_id="op_persist",
        name="Persisted Operator",
        assigned_wallets=3,
        conn=writer,
    )
    assign_task_to_operator(
        title="Persisted task",
        project="Scroll",
        operator_id="op_persist",
        target_wallet_count=2,
        conn=writer,
    )
    writer.close()

    reader = _sqlite3.connect(str(db_file))
    try:
        data = get_team_studio_dashboard(reader)
        assert data["summary"]["active_operators_count"] == 1
        assert data["operators"][0]["operator_id"] == "op_persist"
        assert len(data["assigned_tasks"]) == 1
        assert data["assigned_tasks"][0]["title"] == "Persisted task"
    finally:
        reader.close()


def test_assign_to_unknown_operator_fails_cleanly(db_conn: sqlite3.Connection) -> None:
    res = assign_task_to_operator(
        title="Orphan task",
        project="Nowhere",
        operator_id="op_ghost",
        target_wallet_count=1,
        conn=db_conn,
    )
    assert res["success"] is False
    assert "不存在" in res["error"]


def test_update_existing_operator(db_conn: sqlite3.Connection) -> None:
    register_or_update_operator(operator_id="op_u", name="Before", assigned_wallets=1, conn=db_conn)
    res = register_or_update_operator(operator_id="op_u", name="After", assigned_wallets=2, conn=db_conn)
    assert res["action"] == "updated"
    assert res["operator"]["name"] == "After"

    # 更新要真实写库：重开连接后仍是新值
    data = get_team_studio_dashboard(db_conn)
    assert data["summary"]["active_operators_count"] == 1
    assert data["operators"][0]["name"] == "After"
    assert data["operators"][0]["assigned_wallets"] == 2
