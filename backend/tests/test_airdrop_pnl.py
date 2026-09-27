"""Unit tests for Airdrop PnL Service and API.

账本已落 SQLite（2026-09-23）：默认样例仅首次建表播种（is_default=1），
用户录入 is_default=0。测试通过直连 ``:memory:`` 连接做隔离。
"""

import sqlite3

import pytest

from app.services.airdrop_pnl import (
    DEFAULT_HARVEST_RECORDS,
    add_harvest_record,
    get_pnl_summary,
)


@pytest.fixture
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


def test_get_pnl_summary(db_conn: sqlite3.Connection) -> None:
    """验证收益汇总包含净利润、RoI 倍数与猎人段位."""
    summary = get_pnl_summary(db_conn)
    assert summary["ok"] is True
    assert summary["total_claimed_projects"] >= 4
    assert summary["total_current_value_usd"] > 0
    assert summary["total_ath_value_usd"] > summary["total_current_value_usd"]
    assert "hunter_tier" in summary
    assert "hunter_tier_badge" in summary


def test_add_harvest_record(db_conn: sqlite3.Connection) -> None:
    """验证录入新空投记录并能被立刻纳入汇总."""
    marker = "$PERSIST1"
    new_rec = {
        "project_name": "Test Protocol",
        "token_symbol": marker,
        "amount_claimed": 1000.0,
        "current_price_usd": 1.5,
        "ath_price_usd": 3.0,
        "gas_spent_usd": 12.0,
        "notes": "单元测试记账",
    }
    res = add_harvest_record(new_rec, conn=db_conn)
    assert res["ok"] is True
    assert res["data"]["token_symbol"] == marker

    summary = get_pnl_summary(db_conn)
    matched = [r for r in summary["records"] if r["token_symbol"] == marker]
    assert len(matched) > 0
    assert matched[0]["net_profit_usd"] == 1500.0 - 12.0


def test_default_records_seeded_once_not_duplicated(tmp_path) -> None:
    """默认样例只在空表播种一次：重复 ensure 不得翻倍."""
    import sqlite3 as _sqlite3

    db_file = tmp_path / "pnl_seed.db"
    conn = _sqlite3.connect(str(db_file))
    try:
        first = get_pnl_summary(conn)
        assert first["total_claimed_projects"] == len(DEFAULT_HARVEST_RECORDS)
        second = get_pnl_summary(conn)
        assert second["total_claimed_projects"] == len(DEFAULT_HARVEST_RECORDS)
    finally:
        conn.close()


def test_user_records_persist_across_reopen(tmp_path) -> None:
    """持久化契约：录入后关闭连接、重开同一库 —— 记录必须存活（模拟重启）."""
    import sqlite3 as _sqlite3

    marker = "$REOPEN"
    db_file = tmp_path / "pnl_persist.db"

    writer = _sqlite3.connect(str(db_file))
    add_harvest_record(
        {
            "project_name": "Reopen Project",
            "token_symbol": marker,
            "amount_claimed": 100.0,
            "current_price_usd": 2.0,
            "ath_price_usd": 4.0,
            "gas_spent_usd": 1.0,
        },
        conn=writer,
    )
    writer.close()

    reader = _sqlite3.connect(str(db_file))
    try:
        summary = get_pnl_summary(reader)
        matched = [r for r in summary["records"] if r["token_symbol"] == marker]
        assert len(matched) == 1
        assert matched[0]["net_profit_usd"] == 200.0 - 1.0
        # 默认样例在重开的库里依然只播种一次
        assert summary["total_claimed_projects"] == len(DEFAULT_HARVEST_RECORDS) + 1
    finally:
        reader.close()
