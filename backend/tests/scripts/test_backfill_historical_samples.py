"""回溯脚本的幂等写入测试。

背景：``feedback`` 表没有唯一键，脚本历史上用 ``INSERT OR REPLACE`` 写历史真值，
在 SQLite 里等价于纯插入 —— 重跑一次就把同一批样本再灌一遍，把反馈条数与
强监督计数刷成假数字。这里钉住「重复写入不新增」与「已重复的行能被清掉」。
"""

from __future__ import annotations

import sqlite3

import pytest

from app.db import init_db
from scripts.backfill_historical_samples import dedupe_historical_feedback, insert_historical_feedback


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    init_db(c)
    try:
        yield c
    finally:
        c.close()


def _count(conn, where: str = "1=1", params: tuple = ()) -> int:
    # where 只来自本文件的字面量断言，非外部输入；S608 在此误报
    sql = f"SELECT COUNT(*) FROM feedback WHERE {where}"  # noqa: S608
    return int(conn.execute(sql, params).fetchone()[0])


def test_insert_historical_feedback_is_idempotent(conn):
    assert insert_historical_feedback(conn, "hist-1", "airdropped", "Case One") == 1
    assert insert_historical_feedback(conn, "hist-1", "airdropped", "Case One") == 0

    assert _count(conn, "project_id = ?", ("hist-1",)) == 1


def test_insert_historical_feedback_maps_outcome_to_signal(conn):
    insert_historical_feedback(conn, "hist-1", "airdropped", "Case One")
    insert_historical_feedback(conn, "hist-2", "not_airdropped", "Case Two")

    rows = {
        row["project_id"]: dict(row)
        for row in conn.execute("SELECT project_id, signal, outcome, user_id FROM feedback").fetchall()
    }
    assert rows["hist-1"]["signal"] == "useful"
    assert rows["hist-1"]["outcome"] == "airdropped"
    assert rows["hist-2"]["signal"] == "useless"
    assert rows["hist-2"]["outcome"] == "not_airdropped"
    assert rows["hist-1"]["user_id"] == "historical_backfill"


def test_dedupe_keeps_latest_historical_row(conn):
    # 模拟旧脚本重复灌入：同一项目三条，内容一致
    for _ in range(3):
        conn.execute(
            """
            INSERT INTO feedback (project_id, user_id, signal, outcome)
            VALUES ('hist-1', 'historical_backfill', 'useful', 'airdropped')
            """
        )
    conn.commit()
    latest_id = conn.execute("SELECT MAX(id) FROM feedback WHERE project_id = 'hist-1'").fetchone()[0]

    assert dedupe_historical_feedback(conn) == 2

    rows = conn.execute("SELECT id FROM feedback WHERE project_id = 'hist-1'").fetchall()
    assert [row["id"] for row in rows] == [latest_id]


def test_dedupe_leaves_real_user_feedback_untouched(conn):
    """真实用户对同一项目多条反馈是合法的，不能被清理。"""
    for _ in range(3):
        conn.execute(
            """
            INSERT INTO feedback (project_id, user_id, signal, outcome)
            VALUES ('p-1', 'default', 'correct_outcome', 'airdropped')
            """
        )
    conn.execute(
        """
        INSERT INTO feedback (project_id, user_id, signal, outcome)
        VALUES ('p-1', 'historical_backfill', 'useful', 'airdropped')
        """
    )
    conn.commit()

    assert dedupe_historical_feedback(conn) == 0
    assert _count(conn, "user_id = 'default'") == 3
    assert _count(conn, "user_id = 'historical_backfill'") == 1
