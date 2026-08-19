"""Tests for the settings config endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "settings_test.db"
    monkeypatch.setattr(settings, "db_path", str(db_path))
    app = create_app()
    return TestClient(app)


class TestSettingsConfig:
    def test_settings_config_returns_200(self, client) -> None:
        """端点返回 200 且结构完整。"""
        response = client.get("/api/v1/settings/config")
        assert response.status_code == 200
        body = response.json()
        assert body["ok"] is True
        data = body["data"]

        # 验证所有顶层 key 存在
        for key in ("access", "weights", "flags", "sources", "automation", "platform", "thresholds", "llm"):
            assert key in data, f"missing top-level key: {key}"

    def test_settings_config_no_secrets_leaked(self, client) -> None:
        """返回的数据里不能包含明文密钥。"""
        response = client.get("/api/v1/settings/config")
        data = response.json()["data"]

        # access 不应包含明文 api_key
        assert "api_key" not in data["access"]
        assert "api_key_set" in data["access"]
        assert isinstance(data["access"]["api_key_set"], bool)

        # sources 里的密钥字段只有 has_api_key 布尔值
        for src_name, src in data["sources"].items():
            assert "has_api_key" in src
            assert isinstance(src["has_api_key"], bool)
            # 不应有 token / api_key / bearer 等明文字段
            for k in src:
                assert k not in ("api_key", "token", "bearer_token", "secret"), f"leaked secret field {k} in {src_name}"

    def test_settings_config_weights_sum(self, client) -> None:
        """权重字段完整且可计算。"""
        response = client.get("/api/v1/settings/config")
        weights = response.json()["data"]["weights"]

        weight_keys = [
            "WEIGHT_AIRDROP_SIGNAL",
            "WEIGHT_NARRATIVE_TIMING",
            "WEIGHT_EXECUTION",
            "WEIGHT_TEAM_REPUTATION",
            "WEIGHT_RISK",
            "WEIGHT_TOKENOMICS",
            "WEIGHT_COMPETITION",
            "WEIGHT_TRANSPARENCY",
        ]
        for k in weight_keys:
            assert k in weights
            assert isinstance(weights[k], (int, float))

        total = sum(weights[k] for k in weight_keys)
        assert abs(total - 1.0) < 0.01, f"weights sum = {total}, expected ~1.0"
