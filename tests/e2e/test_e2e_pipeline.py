# ──────────────────────────────────────────────
# E2E Test — Web3 Airdrop Alpha Agent System
# ──────────────────────────────────────────────
# 端到端测试：从 API 触发 pipeline 到结果落库的全链路验证。
# 运行：pytest tests/e2e -v
# 前提：本地或 CI 中启动完整服务栈
# ──────────────────────────────────────────────

from __future__ import annotations

import pytest

BASE_URL = "http://localhost:8000"


@pytest.fixture(scope="module")
def client():
    """提供 HTTP 客户端，可使用 httpx 或 requests。"""
    try:
        import httpx
    except ImportError as exc:
        pytest.skip(f"httpx not installed: {exc}")
    return httpx.Client(base_url=BASE_URL, timeout=30.0)


@pytest.mark.e2e
def test_health_endpoint(client) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "ok"


@pytest.mark.e2e
def test_run_pipeline_and_check_project(client) -> None:
    """触发 pipeline run 并验证项目写入数据库。"""
    # 1. 触发 pipeline
    response = client.post("/api/v1/run", json={"source": "seed", "limit": 5})
    assert response.status_code in (200, 202)

    run_data = response.json()
    assert run_data.get("ok") is True
    inserted = run_data.get("data", {}).get("inserted", 0)
    assert inserted >= 0

    # 2. 短暂等待数据落库
    import time

    time.sleep(2)

    # 3. 验证项目列表非空
    projects_resp = client.get("/api/v1/projects?limit=10")
    assert projects_resp.status_code == 200
    projects = projects_resp.json()
    items = projects.get("data", []) if isinstance(projects.get("data"), list) else []
    assert len(items) >= 1


@pytest.mark.e2e
def test_api_version_header(client) -> None:
    response = client.get("/api/v1/projects?limit=1")
    assert response.status_code == 200
    assert "X-API-Version" in response.headers
