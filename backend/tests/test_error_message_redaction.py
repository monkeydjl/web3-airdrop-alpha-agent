"""采集错误信息入库统一脱敏回归（2026-11-13 审查 P3-11）。

背景：14 处采集器把 `error_message = str(e)` 原样交给持久层 —— httpx 的
异常消息会渲染完整 URL（Etherscan `?apikey=`、带 token 的 webhook 地址等）。
批量路径 `persist_collection_result` 已在落库前 redact，单条路径
`save_collection_result` 漏了（legacy CollectionScheduler 构造的
`error_message=str(e)` 恰好走这条路）。

契约：**collection_logs 落盘的 error_message 一律经过 redact** ——
脱敏是持久层的职责，不依赖 14 个采集器各自记得。
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from app.collectors.base import CollectorResult
from app.collectors.persistence import CollectionRepository
from app.db import init_db


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def _result_with_leaky_error() -> CollectorResult:
    result = CollectorResult(
        source_id="etherscan",
        status="error",
        error_message=("https://api.etherscan.io/api?module=logs&apikey=REALSECRET123 failed: boom"),
    )
    result.started_at = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    result.finished_at = datetime(2026, 11, 13, 12, 1, tzinfo=UTC)
    return result


def test_save_collection_result_redacts_error_message():
    conn = _conn()
    try:
        repo = CollectionRepository(conn)
        repo.save_collection_result(_result_with_leaky_error())

        row = conn.execute("SELECT error_message FROM collection_logs WHERE source_id = 'etherscan'").fetchone()
        assert row is not None
        assert row["error_message"] is not None
        assert "REALSECRET123" not in row["error_message"], (
            f"单条路径把密钥写进了 collection_logs：{row['error_message']!r}"
        )
    finally:
        conn.close()


def test_persist_collection_result_still_redacts():
    """批量路径（既有行为）不得回归。"""
    conn = _conn()
    try:
        repo = CollectionRepository(conn)
        repo.persist_collection_result(_result_with_leaky_error())

        row = conn.execute("SELECT error_message FROM collection_logs WHERE source_id = 'etherscan'").fetchone()
        assert row is not None
        assert row["error_message"] is not None
        assert "REALSECRET123" not in row["error_message"]
    finally:
        conn.close()
