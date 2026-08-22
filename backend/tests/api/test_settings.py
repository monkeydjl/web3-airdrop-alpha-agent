"""Tests for the settings config endpoint."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app

# 一个显眼的假 key，用来在整份响应体里搜它有没有原样漏出去
LEAK_CANARY = "sk-CANARY-must-never-appear-in-any-response"


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

    def test_label_thresholds_match_scorer(self, client) -> None:
        """标签阈值必须等于 scorer 的真值，不能是抄来的第二份常量。

        前端项目详情页曾把「FARM≥65 / WATCH≥50」写死在文案里，而这两个数
        已经改过一次（v1.1：FARM 70 → 65）。这个测试的作用是：以后有人再调
        `LABEL_THRESHOLDS`，如果本端点没跟着变，这里就红——避免又出现一份
        静默说谎的副本。
        """
        from app.agents.scorer import LABEL_THRESHOLDS

        thresholds = client.get("/api/v1/settings/config").json()["data"]["thresholds"]
        expected = {name: value for value, name in LABEL_THRESHOLDS}

        assert thresholds["LABEL_FARM_THRESHOLD"] == expected["FARM"]
        assert thresholds["LABEL_WATCH_THRESHOLD"] == expected["WATCH"]
        # 顺序也必须成立：FARM 门槛严于 WATCH
        assert thresholds["LABEL_FARM_THRESHOLD"] > thresholds["LABEL_WATCH_THRESHOLD"]

    def test_label_threshold_helper_rejects_unknown_label(self) -> None:
        """拼错标签名时返回 0，而不是某个看起来像真值的数字。"""
        from app.routers.v1.settings import _label_threshold

        assert _label_threshold("FARM") > 0
        assert _label_threshold("NOT_A_LABEL") == 0


class TestSettingsConfigLlmKeyRedaction:
    """回归：`/settings/config` 曾直接回显 settings.llm_providers 里的明文 api_key。

    配合公开的 /auth/anonymous（任何人可领匿名 token），构成零凭证窃取
    OPENAI_API_KEY 的完整链路。这组测试锁死"密钥永不出现在响应体里"。
    """

    def test_llm_providers_never_expose_raw_api_key(self, client, monkeypatch) -> None:
        """配置了 LLM key 时，响应体全文都不得出现该 key。"""
        monkeypatch.setattr(settings, "openai_api_key", LEAK_CANARY)

        response = client.get("/api/v1/settings/config")
        assert response.status_code == 200

        # 关键断言：整份响应体（含嵌套结构）搜不到明文
        assert LEAK_CANARY not in response.text

        providers = response.json()["data"]["llm"]["providers"]
        assert providers, "provider list should not be empty when a key is configured"
        for p in providers:
            assert "api_key" not in p, "provider must not carry a raw api_key field"
            assert p["has_api_key"] is True
            # 只暴露非敏感元信息
            assert set(p) <= {"name", "base_url", "has_api_key", "models"}

    def test_llm_providers_report_missing_key(self, client, monkeypatch) -> None:
        """未配置 key 时不应伪造 has_api_key=True。"""
        monkeypatch.setattr(settings, "openai_api_key", "")

        response = client.get("/api/v1/settings/config")
        for p in response.json()["data"]["llm"]["providers"]:
            assert p["has_api_key"] is False


class TestSettingsRequiresAdmin:
    """回归：/api/v1/settings 必须是管理员专属（匿名 token 不可读）。

    运行时配置快照含 CORS 白名单、DB 后端、全部阈值与 cron —— 对匿名开放
    等于免费给攻击者做侦察。
    """

    ADMIN_KEY = "admin-key-for-settings-tests-0123456789"

    @pytest.fixture
    def auth_client(self, tmp_path, monkeypatch):
        monkeypatch.setattr(settings, "db_path", str(tmp_path / "settings_auth.db"))
        monkeypatch.setattr(settings, "api_key", self.ADMIN_KEY)
        monkeypatch.setattr(settings, "auth_token_secret", "secret-for-settings-admin-tests")
        monkeypatch.setattr(settings, "rate_limit_enabled", False)
        return TestClient(create_app())

    def test_settings_in_admin_only_prefixes(self) -> None:
        from app.auth import ADMIN_ONLY_PREFIXES

        assert "/api/v1/settings" in ADMIN_ONLY_PREFIXES

    def test_no_credentials_rejected(self, auth_client) -> None:
        assert auth_client.get("/api/v1/settings/config").status_code == 401

    def test_anonymous_token_forbidden(self, auth_client) -> None:
        """匿名 token 能领到，但读不了 settings。"""
        token = auth_client.post("/api/v1/auth/anonymous").json()["access_token"]

        response = auth_client.get(
            "/api/v1/settings/config",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    def test_admin_key_allowed(self, auth_client) -> None:
        response = auth_client.get(
            "/api/v1/settings/config",
            headers={"X-API-Key": self.ADMIN_KEY},
        )
        assert response.status_code == 200
