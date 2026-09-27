"""connection_scope 契约测试（CONVENTIONS.md §13.3）。

连接所有权是全仓 borrow/own 契约的权威实现点：这里锁住它的三种合法
用法与两种非法/危险形态，防止未来回归成「with 误关借用连接」。
"""

from __future__ import annotations

import pytest

from app.db import DbConnection, connection_scope, get_connection


class _TrackingConn:
    """包装 DbConnection 以统计 close 次数（保留其余行为）。"""

    def __init__(self, conn: DbConnection) -> None:
        self._conn = conn
        self.close_calls = 0

    def execute(self, sql: str, params: object = None) -> object:
        return self._conn.execute(sql, params)  # type: ignore[arg-type]

    def commit(self) -> None:
        self._conn.commit()

    def rollback(self) -> None:
        self._conn.rollback()

    def close(self) -> None:
        self.close_calls += 1
        self._conn.close()


def _fresh_conn() -> DbConnection:
    return get_connection()


class TestShortScope:
    def test_borrow_never_closed(self) -> None:
        """注入的共享连接在作用域内使用、退出后必须仍然可用。"""
        tracked = _TrackingConn(_fresh_conn())
        with connection_scope(tracked) as conn:  # type: ignore[arg-type]
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        assert tracked.close_calls == 0
        # 借用连接作用域外仍然可用（这是 17.1.26 锚定的核心契约）。
        assert tracked.execute("SELECT 1").fetchone()[0] == 1
        tracked.close()

    def test_own_closes_exactly_once(self) -> None:
        """无注入时作用域自建连接并在退出时关闭恰一次。"""
        with connection_scope() as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        # 作用域已关闭：再执行应报错（sqlite ProgrammingError）。
        import sqlite3

        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")

    def test_scope_closes_on_exception(self) -> None:
        """own 连接在作用域异常时也必须被关闭（不泄漏）。"""
        with pytest.raises(RuntimeError, match="boom"), connection_scope() as conn:
            raise RuntimeError("boom")
        import sqlite3

        with pytest.raises(sqlite3.ProgrammingError):
            conn.execute("SELECT 1")


class TestFactoryForm:
    def test_own_factory_closes(self) -> None:
        """owns=True 的 factory 消费者：连接用后即关（生产 get_connection 语义）。"""
        made: list[DbConnection] = []

        def factory() -> DbConnection:
            conn = _fresh_conn()
            made.append(conn)
            return conn

        with connection_scope(factory=factory, owns=True) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        assert len(made) == 1
        import sqlite3

        with pytest.raises(sqlite3.ProgrammingError):
            made[0].execute("SELECT 1")

    def test_borrow_factory_never_closes(self) -> None:
        """owns=False 的 factory 消费者（LeaderElector + db_override 形态）：
        factory 返回的借用共享连接永不被消费方关闭。"""
        tracked = _TrackingConn(_fresh_conn())
        calls = {"n": 0}

        def factory() -> DbConnection:
            calls["n"] += 1
            return tracked  # type: ignore[return-value]

        with connection_scope(factory=factory, owns=False) as conn:
            assert conn.execute("SELECT 1").fetchone()[0] == 1
        assert calls["n"] == 1
        assert tracked.close_calls == 0
        # 作用域退出后共享连接仍可用（lifespan 后续消费者依赖这一点）。
        assert tracked.execute("SELECT 1").fetchone()[0] == 1
        tracked.close()


class TestMisuse:
    def test_conn_and_factory_are_mutually_exclusive(self) -> None:
        """conn 与 factory 同时给以 ValueError 拒绝（防静默歧义）。"""
        tracked = _TrackingConn(_fresh_conn())

        def factory() -> DbConnection:
            return tracked  # type: ignore[return-value]

        with pytest.raises(ValueError, match="conn or factory"), connection_scope(tracked, factory=factory):  # type: ignore[arg-type]
            pass
        assert tracked.close_calls == 0
        tracked.close()


class TestElectorWiring:
    def test_leader_elector_defaults_to_own(self) -> None:
        """生产路径：默认 conn_factory=get_connection 必须 own（用后即关）。"""
        from app.services.leader_election import LeaderElector

        elector = LeaderElector(instance_id="it_scope_own", enabled=False)
        assert elector.owns_connections is True

    def test_leader_elector_accepts_borrow_flag(self) -> None:
        """db_override 注入路径：main.py 传 owns_connections=False。"""
        from app.services.leader_election import LeaderElector

        tracked = _TrackingConn(_fresh_conn())
        elector = LeaderElector(
            lambda: tracked,  # type: ignore[arg-type, return-value]
            instance_id="it_scope_borrow",
            enabled=False,
            owns_connections=False,
        )
        assert elector.owns_connections is False
        # start/stop（standalone）全程不 touch 连接。
        import asyncio

        asyncio.run(elector.start())
        asyncio.run(elector.stop())
        assert tracked.close_calls == 0
        assert tracked.execute("SELECT 1").fetchone()[0] == 1
        tracked.close()
