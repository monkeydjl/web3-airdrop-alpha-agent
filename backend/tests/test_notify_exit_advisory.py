"""exit_advisory 事件闭环回归（2026-11-19 深审 P0）。

背景：evaluator 会产出 `exit_advisory`（止损撤退预警：官网离线 / 代码
停更），但 metrics.NOTIFY_EVENT_TYPES 闭合词表没有登记它——
`insert_event` 对表外类型必抛 ValueError，而 `_collect_and_store` 在
`conn.commit()` 之前逐条入库：只要当天有任一项目触发 exit_advisory，
**整批事件（含 digest）在提交前全部回滚**，每日摘要 job 天天失败，
该特性从未能发出过一条消息。

契约：
1. evaluator 能产出的每一种 event_type 都必须登记进 NOTIFY_EVENT_TYPES
   （静态同步钉，新增事件类型忘登记会让 CI 变红）；
2. 触发止损预警的项目（meta.signals.site_alive=false）不再炸掉整批
   入库——exit_advisory 与 digest 都能落 notify_log。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, datetime

import pytest

from app.db import init_db
from app.metrics import NOTIFY_EVENT_TYPES
from app.notify.evaluator import evaluate_events


def _fresh_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _seed_degrading_project(conn: sqlite3.Connection, project_id: str = "p-exit-1") -> None:
    """一个官网失联的项目：meta.signals.site_alive=false，updated_at 在今天。"""
    meta = {
        "signals": {"site_alive": False},
        "funding": {"total_raised": 1_000_000},
    }
    conn.execute(
        """
        INSERT INTO projects (id, name, url, sector, stage, score, label, confidence,
                              weight_version, meta, updated_at, source)
        VALUES (?, 'Degrading Project', 'https://degrading.example.com', 'DeFi', 'mainnet',
                70, 'FARM', 0.8, 'v1.2', ?, ?, 'test')
        """,
        (project_id, json.dumps(meta), datetime.now(UTC).isoformat()),
    )
    conn.commit()


def test_evaluator_event_types_are_all_registered() -> None:
    """静态同步钉：evaluator 能产出的每种 event_type 都必须在闭合词表里。"""
    from app.notify import evaluator

    src = __import__("inspect").getsource(evaluator)
    literals = set(re.findall(r'event_type="([a-z_]+)"', src))
    assert literals, "解析不到 evaluator 的 event_type 字面量 —— 正则已失效"
    unregistered = literals - NOTIFY_EVENT_TYPES
    assert not unregistered, (
        f"evaluator 产出了未登记的事件类型 {sorted(unregistered)} —— insert_event 会在入库时抛 ValueError，整批事件回滚"
    )


def test_exit_advisory_event_reaches_notify_log_without_rolling_back_batch() -> None:
    """触发止损预警的项目不得炸掉整批入库（修复前：ValueError → 全部回滚）。"""
    conn = _fresh_conn()
    try:
        _seed_degrading_project(conn, "p-exit-1")
        # _collect_and_store 自管连接（connection_scope）——对内存库不可注入，
        # 这里先直接驱动 evaluate_events + insert_event 复刻入库流程，
        # 再在下方用 monkeypatch 走 service 层端到端。
        events = evaluate_events(conn, include_digest=True)
        types = [e.event_type for e in events]
        assert "exit_advisory" in types, f"evaluator 未产出 exit_advisory（事件类型：{types}）—— 触发条件或种子不成立"

        from app.config import settings
        from app.notify.service import insert_event

        inserted_n = 0
        for event in events:
            if insert_event(conn, event, settings.notify_channel):
                inserted_n += 1
        conn.commit()

        rows = conn.execute("SELECT DISTINCT event_type FROM notify_log").fetchall()
        logged = {dict(r)["event_type"] for r in rows}
        assert "exit_advisory" in logged, f"exit_advisory 未落 notify_log：{logged}"
        assert "daily_digest" in logged, "同批的 digest 也应落库"
        assert inserted_n >= len(events) - 1 or inserted_n >= 1
        assert inserted_n == len([e for e in events])
    finally:
        conn.close()


def test_collect_and_store_completes_with_exit_advisory(monkeypatch: pytest.MonkeyPatch) -> None:
    """service 层端到端：exit_advisory 在场时 _collect_and_store 正常完成。"""
    from app.notify import service as notify_service

    conn = _fresh_conn()
    _seed_degrading_project(conn, "p-exit-2")

    import contextlib

    @contextlib.contextmanager
    def scope(*args: object, **kwargs: object):
        yield conn

    monkeypatch.setattr(notify_service, "connection_scope", scope)

    inserted = notify_service._collect_and_store(include_digest=True)
    assert inserted >= 1

    rows = conn.execute("SELECT DISTINCT event_type FROM notify_log").fetchall()
    logged = {dict(r)["event_type"] for r in rows}
    assert "exit_advisory" in logged
    conn.close()
