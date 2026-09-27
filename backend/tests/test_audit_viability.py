"""Unit tests for Batch Viability Audit script."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from app.db import dict_from_row, get_connection

# 显式建库：此文件的用例直连 DB_PATH 但自身不 init_db()，过去依赖
# conftest pytest_configure 的会话级兜底（主仓库 data/test.db 的历史残留
# schema）侥幸通过；全新 checkout / CI runner 上单跑必红（no such table）。
# 现改为模块内显式 autouse fixture 幂等建库，消除对兜底的隐式依赖。

import pytest


@pytest.fixture(autouse=True)
def _ensure_db_schema():
    """显式幂等建库（不删库、不清数据）；详见文件头注释。"""
    from app.db import init_db

    init_db()


from app.opportunity.decision import LOW_RUNWAY_RISK
from app.services.viability_gate import UNBACKED_POINTS_MACHINE
from scripts.audit_viability import run_viability_audit


def test_run_viability_audit_dry_run():
    """Audit executes in dry-run mode without errors and returns structured metrics."""
    report = run_viability_audit(apply_changes=False)

    assert "total_scanned" in report
    assert "tier_counts" in report
    assert "reason_counts" in report
    assert "downgraded_count" in report
    assert "downgraded_projects" in report
    assert report["applied"] is False

    assert report["total_scanned"] >= 0
    assert "viable" in report["tier_counts"]
    assert "borderline" in report["tier_counts"]
    assert "unviable" in report["tier_counts"]


def test_run_viability_audit_downgrade_logic():
    """Test that an unbacked points machine with FARM label is downgraded."""
    conn = get_connection()
    now = datetime.now(UTC)
    test_id = "test-unbacked-pts-audit"

    try:
        # 插入一个模拟的零融资纯积分盘 FARM 项目
        meta = {
            "signals": {
                "has_points_program": True,
                "funding_total_usd": 0,
                "funding_tier": "none",
                "tvl_usd": 0,
            }
        }
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (
                id, name, sector, stage, score, label, confidence, reason, meta, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                test_id,
                "Test Unbacked Points",
                "defi",
                "mainnet",
                85,
                "FARM",
                0.9,
                json.dumps(["strong airdrop signal"]),
                json.dumps(meta),
                now,
                now,
            ),
        )
        conn.commit()

        # 执行 dry-run
        report = run_viability_audit(apply_changes=False)
        downgraded_ids = [p["id"] for p in report["downgraded_projects"]]
        assert test_id in downgraded_ids

        target = next(p for p in report["downgraded_projects"] if p["id"] == test_id)
        assert target["from_label"] == "FARM"
        assert target["to_label"] == "IGNORE"
        assert UNBACKED_POINTS_MACHINE in target["reasons"]

        # 执行 apply 模式
        apply_report = run_viability_audit(apply_changes=True)
        assert apply_report["applied"] is True

        # 验证数据库真实更新
        row = conn.execute("SELECT label, reason, meta FROM projects WHERE id = ?", (test_id,)).fetchone()
        assert row is not None
        d = dict_from_row(row)
        assert d["label"] == "IGNORE"
        reasons = json.loads(d["reason"])
        assert LOW_RUNWAY_RISK in reasons
        meta_d = json.loads(d["meta"])
        assert meta_d["viability_tier"] == "unviable"

    finally:
        # 清理测试数据
        conn.execute("DELETE FROM projects WHERE id = ?", (test_id,))
        conn.commit()
        conn.close()
