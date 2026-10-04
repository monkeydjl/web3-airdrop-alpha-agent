"""Unit tests for ROI simulator service and endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import get_connection, init_db
from app.main import app
from app.services.roi_simulator import simulate_portfolio_allocation, simulate_project_roi


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """把默认库重定向到 tmp_path 并自播种 FARM 项目。

    历史教训（2026-09-29 conftest 改为每轮删除默认库后暴露）：本文件原先直接
    调 service，既不改 ``db_path`` 也不播种，隐式依赖默认库里的历史残留行。
    空库下 ``simulate_portfolio_allocation`` 落到两条查询都为空的分支，返回
    ``allocations == []``，``assert len(...) > 0`` 当场红——且只在冷库（CI /
    新鲜 clone）复现，本机跑过其它测试后又被残留行"治好"。

    这里显式建库 + 播种，让用例对默认库内容零依赖，满足空库酸测口径。
    """
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "test.db"))
    init_db()
    _seed_farm_projects()
    yield


def _seed_farm_projects() -> None:
    """播种覆盖三个分配桶的 FARM 项目：restaking / testnet / community。

    只需 id/name/sector/stage/score 存在即可驱动分配逻辑（``source`` 留 NULL
    以匹配 ``source != 'historical_backfill' OR source IS NULL`` 过滤）。
    """
    with get_connection() as conn:
        for pid, name, sector, stage, score in (
            ("roi-defi-1", "Restake Alpha", "defi", "mainnet", 88),
            ("roi-testnet-2", "Testnet Beta", "infra", "testnet", 82),
            ("roi-comm-3", "Community Gamma", "community", "testnet", 70),
        ):
            conn.execute(
                "INSERT INTO projects (id, name, sector, stage, score, label) VALUES (?, ?, ?, ?, ?, 'FARM')",
                (pid, name, sector, stage, score),
            )
        conn.commit()


def test_simulate_project_roi_not_found(isolated_db) -> None:
    res = simulate_project_roi("non-existent-id")
    assert res["ok"] is False
    assert "not found" in res["error"]


def test_simulate_portfolio_allocation(isolated_db) -> None:
    res = simulate_portfolio_allocation(total_budget_usd=300.0, weekly_hours=5.0)
    assert res["ok"] is True
    data = res["data"]
    assert data["total_budget_usd"] == 300.0
    assert data["weekly_hours"] == 5.0
    assert len(data["allocations"]) > 0
    assert data["total_expected_return_usd"] > 0
    assert data["portfolio_roi_multiple"] > 0
    assert "summary_advice" in data


def test_simulate_portfolio_allocation_empty_db(tmp_path, monkeypatch) -> None:
    """空库必须优雅返回零分配而非报错——显式钉住回退口径。

    这是冷库回归钉：此前的失败正是"空库返回空分配"被当成 bug，实际是测试
    自己没播种。空库语义是有意的（无 FARM 项目时不该编造配置）。
    """
    monkeypatch.setattr(settings, "db_path", str(tmp_path / "empty.db"))
    init_db()
    res = simulate_portfolio_allocation(total_budget_usd=300.0, weekly_hours=5.0)
    assert res["ok"] is True
    assert res["data"]["allocations"] == []
    assert res["data"]["total_expected_return_usd"] == 0.0


def test_roi_simulation_api_endpoints(isolated_db) -> None:
    client = TestClient(app)

    # Test POST /api/v1/roi/simulate/portfolio
    payload = {
        "total_budget_usd": 400.0,
        "weekly_hours": 6.0,
        "risk_appetite": "balanced",
    }
    res = client.post("/api/v1/roi/simulate/portfolio", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert data["data"]["total_budget_usd"] == 400.0
    # 端点端到端也要真的产出配置——只断言 ok/budget 会让"空库返回空配置"漏网。
    assert len(data["data"]["allocations"]) > 0
    assert data["data"]["total_expected_return_usd"] > 0
