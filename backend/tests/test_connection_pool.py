"""SQLite 连接池回归（2026-11-13 审查 P2-1）。

背景：每次建连都执行一整套 PRAGMA（`cache_size=-64000` 即 64MB 页缓存是
**每连接**的）+ WAL 模式设置 —— 每请求新建连接的成本远不止一次 open。
池挂在 `get_connection()` 下，`connection_scope` 的 own 契约（close 恰一次）
语义不变：close 的含义变成"归还池"。

安全设计：
- **APP_ENV=test 时整体关闭** —— 测试环境 db_path 被 per-test monkeypatch、
  库文件被会话级删除重建，池化会把"句柄指向已删除文件"这类竞态引进来；
- close 归还前先 rollback（清掉遗留事务，不给下一个借用者接半截事务）；
- 借用与归还两侧都校验库文件仍存在（会话级删库重建场景）；
- 每个 db_path 独立成池（键控），永不跨路径复用；池满真关。
"""

from __future__ import annotations

import pytest

from app.config import settings
from app.db import DbConnection, _sqlite_pool, get_connection


@pytest.fixture
def pool_enabled(monkeypatch: pytest.MonkeyPatch, tmp_path) -> str:
    """开启池化并指向独立的 tmp 库文件；返回该路径。"""
    monkeypatch.setattr(settings, "app_env", "development")
    db_path = str(tmp_path / "pool-test.db")
    monkeypatch.setattr(settings, "db_path", db_path)
    return db_path


def test_pool_disabled_under_test_env(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """APP_ENV=test（conftest 默认）时池必须整体关闭：拿到的是普通连接。"""
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "plain.db"))
    conn = get_connection()
    assert type(conn) is DbConnection, "测试环境不应拿到池化连接"
    conn.close()


def test_repeated_acquires_reuse_the_pooled_connection(pool_enabled: str) -> None:
    conn_a = get_connection()
    raw_a = conn_a._raw
    conn_a.close()

    conn_b = get_connection()
    try:
        assert conn_b._raw is raw_a, "池化后重复建连 —— PRAGMA 成本回来了"
    finally:
        conn_b.close()


def test_return_rolls_back_uncommitted_work(pool_enabled: str) -> None:
    conn_a = get_connection()
    conn_a.execute("CREATE TABLE IF NOT EXISTS pool_probe (id INTEGER PRIMARY KEY, tag TEXT)")
    conn_a.commit()
    conn_a.execute("INSERT INTO pool_probe (tag) VALUES ('uncommitted')")
    conn_a.close()  # 归还：未提交事务必须被回滚

    conn_b = get_connection()
    try:
        row = conn_b.execute("SELECT COUNT(*) AS c FROM pool_probe").fetchone()
        count = row["c"] if hasattr(row, "keys") else row[0]
        assert count == 0, "归还时未回滚遗留事务 —— 下一个借用者接到半截写入"
    finally:
        conn_b.close()


def test_pool_is_capped_per_path(pool_enabled: str) -> None:
    from app.db import _SQLITE_POOL_MAX_PER_PATH

    for _ in range(_SQLITE_POOL_MAX_PER_PATH + 2):
        conn = get_connection()
        conn.close()

    key = next(iter(_sqlite_pool))
    assert len(_sqlite_pool[key]) <= _SQLITE_POOL_MAX_PER_PATH, f"池未被封顶：{len(_sqlite_pool[key])}"


def test_deleted_db_file_not_reused(pool_enabled: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """借用侧校验库文件存在 —— 会话级删库重建不接幽灵句柄。

    Windows 上池内句柄会占住文件（os.remove 报 PermissionError），
    所以用 monkeypatch 模拟"文件已消失"；POSIX 上删库重建走的同一守卫。
    """
    import os as os_mod

    import app.db as db_mod

    conn_a = get_connection()
    raw_a = conn_a._raw
    conn_a.close()  # 入池

    real_exists = os_mod.path.exists

    def _file_gone(path: object) -> bool:
        return False if str(path) == pool_enabled else real_exists(path)

    monkeypatch.setattr(db_mod.os.path, "exists", _file_gone)

    conn_b = get_connection()
    try:
        assert conn_b._raw is not raw_a, "指向已删除文件的连接被复用 —— 写进幽灵文件"
    finally:
        conn_b.close()


def test_pool_keys_are_per_path(pool_enabled: str, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """不同 db_path 各自成池，永不跨路径复用。"""
    other_path = str(tmp_path / "other.db")

    conn_a = get_connection()
    raw_a = conn_a._raw
    conn_a.close()

    monkeypatch.setattr(settings, "db_path", other_path)
    conn_b = get_connection()
    try:
        assert conn_b._raw is not raw_a, "不同 db_path 的连接被跨池复用"
    finally:
        conn_b.close()
