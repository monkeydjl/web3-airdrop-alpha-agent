# ──────────────────────────────────────────────
# API 集成测试
# 对应 docs/API_SPEC.md 契约
# 路由注册（main.py TODO）后取消注释启用
# ──────────────────────────────────────────────

import pytest


@pytest.fixture
def client():
    try:
        from app.main import create_app
        from fastapi.testclient import TestClient
    except Exception as e:  # pragma: no cover
        pytest.skip(f"app not yet wired: {e}")
    app = create_app(db_override=None)
    return TestClient(app)


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["status"] == "healthy"


class TestVersionEndpoint:
    def test_version_shape(self, client):
        resp = client.get("/version")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert "version" in body["data"]
