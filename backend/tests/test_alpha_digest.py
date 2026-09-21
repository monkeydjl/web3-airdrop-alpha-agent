"""Unit tests for Alpha Digest Generator service and API endpoint."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.alpha_digest import generate_alpha_digest


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_generate_alpha_digest_direct():
    result = generate_alpha_digest(window_days=7, min_score=60.0, limit=10)
    assert result["ok"] is True
    assert "markdown" in result
    assert "summary" in result

    md = result["markdown"]
    assert "# 🦅 Web3 Alpha 深度投研周报" in md
    assert "1. 📊 核心宏观态势与雷达概览" in md
    assert "2. 🌟 本周 Top Alpha 精选项目清单" in md
    assert "3. 🛡️ 零资金成本测试网优先专区" in md
    assert "4. ⚠️ 防 PUA 疲劳指数与风险避坑雷达" in md
    assert "5. 💼 多钱包防女巫操作守则与资金配置建议" in md

    summary = result["summary"]
    assert summary["window_days"] == 7
    assert summary["total_scanned"] >= 0
    assert "total_farm" in summary
    assert "total_zero_cost" in summary
    assert "avg_top_score" in summary


def test_get_projects_digest_endpoint(client):
    resp = client.get("/api/v1/projects/digest?window_days=14&min_score=65.0&limit=5")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ok"] is True
    assert isinstance(data["markdown"], str)
    assert data["summary"]["window_days"] == 14
