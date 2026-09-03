"""公开配置端点 `GET /api/v1/public-config` 的边界测试（2026-09-03 新增）。

## 这个端点为什么存在

前端项目详情页要展示"这个分是按什么权重、什么阈值算出来的"，而这两组数
**已经被调过**（v1.1 把 FARM 从 70 下调到 65）。写死在前端的数字不会跟着改，
只会静默变成错的。

但 `/settings/config` 回显 `has_api_key`、各源 `base_url`、全部 cron、
LLM 预算与兜底单价、`DB_BACKEND` / `APP_ENV` —— 一份完整的基础设施画像，
必须留在管理员锁后面。此前前端代理把管理员密钥无差别注入所有 `/api/*`，
于是面向访客的详情页也能读到那份画像。

## 本文件守什么

1. **匿名可读**：否则拆了等于没拆（前端代理改成只给管理动作注入密钥后，
   这个端点必须能用匿名 token 读到）。
2. **不含敏感字段**：白名单必须是白名单。将来给 `/settings/config`
   加字段时，本端点不能跟着漏 —— 这是最容易发生的回归。
3. **与 `/settings/config` 的阈值一致**：两个端点报不同的 FARM 阈值比报错更坏。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import create_app

ADMIN_KEY = "k" * 40


@pytest.fixture
def client(monkeypatch):
    """带鉴权的 app。

    必须显式设 `api_key` —— 留空时后端是 MVP 无鉴权模式，所有请求都放行，
    那样测出来的 200 不能说明任何事（此前踩过：环境残留导致误判）。
    """
    monkeypatch.setattr(settings, "api_key", ADMIN_KEY)
    monkeypatch.setattr(settings, "auth_token_secret", "s" * 50)
    with TestClient(create_app()) as c:
        yield c


def _anon_headers(client) -> dict[str, str]:
    resp = client.post("/api/v1/auth/anonymous")
    assert resp.status_code == 200, f"匿名 token 签发失败：{resp.status_code}"
    # 注意该端点**不用** {ok, data} 信封（与其它 v1 端点不同）
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


class TestAnonymousCanRead:
    def test_anonymous_token_gets_200(self, client):
        resp = client.get("/api/v1/public-config", headers=_anon_headers(client))
        expected = (
            "匿名读不到就等于没拆分 —— 前端代理已改成只给管理动作注入管理员密钥，项目详情页会因此拿不到权重与阈值"
        )
        assert resp.status_code == 200, expected

    def test_no_credentials_still_gets_401(self, client):
        """「非管理员」不等于「免鉴权」。

        后端中间件在 api_key 非空时要求任何请求都带凭据，匿名 token 也是凭据。
        这条钉住的是：不能为了让前端省事就把本端点塞进 PUBLIC_PREFIXES。
        """
        assert client.get("/api/v1/public-config").status_code == 401

    def test_admin_key_also_works(self, client):
        """管理员凭据当然也能读 —— 降权不该反过来把管理员挡在外面。"""
        resp = client.get("/api/v1/public-config", headers={"X-API-Key": ADMIN_KEY})
        assert resp.status_code == 200

    def test_settings_config_stays_admin_only(self, client):
        """对照组：`/settings/config` 必须仍然锁着，否则这次拆分毫无意义。"""
        assert client.get("/api/v1/settings/config", headers=_anon_headers(client)).status_code == 403
        assert client.get("/api/v1/settings/config", headers={"X-API-Key": ADMIN_KEY}).status_code == 200


class TestPayloadShape:
    def test_returns_eight_weights_plus_version(self, client):
        data = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        weights = data["weights"]
        assert len([k for k in weights if k.startswith("WEIGHT_")]) == 8
        assert "weight_version" in weights, "前端要显示这个分是哪一版权重算的"

    def test_weights_sum_to_one(self, client):
        """权重和必须是 1.0 —— 前端按它做百分比展示。"""
        data = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        total = sum(v for k, v in data["weights"].items() if isinstance(v, (int, float)))
        assert abs(total - 1.0) < 1e-9, f"权重和是 {total}，不是 1.0"

    def test_label_thresholds_present(self, client):
        data = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        th = data["thresholds"]
        assert th["LABEL_FARM_THRESHOLD"] > th["LABEL_WATCH_THRESHOLD"] > 0

    def test_thresholds_match_settings_config_exactly(self, client):
        """两个端点报的阈值必须一致。

        `public_config.py` 刻意复用 `settings.py` 的 `_label_threshold` 而不是
        抄第三份查表逻辑（抄的那一版凭印象写成 `.get()`，而 LABEL_THRESHOLDS
        是元组列表，直接 AttributeError）。这条钉住"别再抄一份"。
        """
        pub = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        adm = client.get("/api/v1/settings/config", headers={"X-API-Key": ADMIN_KEY}).json()["data"]
        for key in ("LABEL_FARM_THRESHOLD", "LABEL_WATCH_THRESHOLD", "CONFIDENCE_THRESHOLD"):
            assert pub["thresholds"][key] == adm["thresholds"][key], f"{key} 两端不一致"

    def test_weights_match_settings_config_exactly(self, client):
        pub = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        adm = client.get("/api/v1/settings/config", headers={"X-API-Key": ADMIN_KEY}).json()["data"]
        assert pub["weights"] == adm["weights"]


class TestNoSensitiveLeakage:
    """白名单必须是白名单 —— 这是最容易发生的回归。"""

    # 每一项都真实出现在 `/settings/config` 的响应里
    FORBIDDEN_SUBSTRINGS = (
        "has_api_key",  # 哪些密钥已配置
        "base_url",  # 采集源地址
        "cron",  # 全部调度表达式
        "DB_BACKEND",  # 用的哪种数据库
        "APP_ENV",  # 环境标识
        "BUDGET",  # LLM 日预算
        "PRICE",  # 兜底单价
        "providers",  # LLM 提供方清单
        "cors_origins",
        "rate_limit",
        "api_key_set",
    )

    def test_response_body_contains_no_infrastructure_fields(self, client):
        body = client.get("/api/v1/public-config", headers=_anon_headers(client)).text
        leaked = [s for s in self.FORBIDDEN_SUBSTRINGS if s in body]
        message = f"公开端点泄露了基础设施字段：{leaked}。本端点是白名单 —— 给 /settings/config 加字段时不该跟着漏出来"
        assert not leaked, message

    def test_top_level_keys_are_exactly_two(self, client):
        """只允许 weights 与 thresholds 两块。

        多出任何一块都要人来确认它该不该匿名可见，所以这里用精确相等
        而不是"包含"。
        """
        data = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        assert set(data) == {"weights", "thresholds"}, f"多了或少了顶层块：{sorted(data)}"

    def test_only_whitelisted_thresholds_are_exposed(self, client):
        """`thresholds` 块在 /settings/config 里混着 LLM 成本配置，这里必须只有三项。"""
        data = client.get("/api/v1/public-config", headers=_anon_headers(client)).json()["data"]
        assert set(data["thresholds"]) == {
            "LABEL_FARM_THRESHOLD",
            "LABEL_WATCH_THRESHOLD",
            "CONFIDENCE_THRESHOLD",
        }
