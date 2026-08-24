"""Tests for multi-provider / multi-model LLM failover client.

配置格式（编号制，每个接口一组变量）：
    LLM_BASEURL_1=https://api.openai.com/v1
    LLM_API_KEY_1=sk-xxx
    LLM_MODELS_1_1=gpt-4o-mini
    LLM_MODELS_1_2=gpt-4o

    LLM_BASEURL_2=https://api.deepseek.com/v1
    LLM_API_KEY_2=sk-yyy
    LLM_MODELS_2_1=deepseek-chat
"""

from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.client import (
    LLMProvider,
    _build_combinations,
    _is_connection_error,
    _is_model_error,
    _RawCompletion,
    llm_chat,
)

# ── 辅助函数 ──────────────────────────────────


def _completion(text: str, *, usage: dict | None = None) -> _RawCompletion:
    """构造 `_try_single` 的返回值。

    `_try_single` 现在返回 `_RawCompletion`（文本 + 接口自报 usage），
    不再是裸字符串 —— 预算拦截需要 token 数才能算钱。

    用 dataclass 而不是 `tuple[str, dict]` 是有意的：如果某个 mock 还返回裸
    字符串，元组解包会把 `"ab"` 静默拆成 `text="a"`, `usage="b"`；
    dataclass 会在 `.text` 上立刻 AttributeError。
    """
    return _RawCompletion(text=text, raw_usage=usage)


def _mock_settings(providers: list[dict]) -> MagicMock:
    """构造只关心故障转移的 settings。

    `llm_daily_budget_usd = 0.0` = 不限额，让这一组用例专注于故障转移本身、
    不碰账本 DB。预算行为另有 `test_llm_budget_enforcement.py` 专门覆盖 ——
    **一个用例同时测两件事，挂掉时分不清是哪件坏了。**
    """
    mock = MagicMock()
    mock.llm_providers = providers
    mock.llm_temperature = 0.3
    mock.llm_max_tokens = 512
    mock.llm_daily_budget_usd = 0.0
    mock.llm_fallback_price_per_1m_usd = 10.0
    return mock


def _clear_llm_env(monkeypatch):
    """清除所有 LLM 相关环境变量。"""
    for i in range(1, 6):
        for prefix in ("LLM_BASEURL_", "LLM_API_KEY_"):
            monkeypatch.delenv(f"{prefix}{i}", raising=False)
        for j in range(1, 6):
            monkeypatch.delenv(f"LLM_MODELS_{i}_{j}", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")


def _setup_provider_1(monkeypatch, models=None):
    """配置接口 1。"""
    monkeypatch.setenv("LLM_BASEURL_1", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_API_KEY_1", "sk-openai-xxx")
    if models:
        for j, m in enumerate(models, 1):
            monkeypatch.setenv(f"LLM_MODELS_1_{j}", m)


def _setup_provider_2(monkeypatch, models=None):
    """配置接口 2。"""
    monkeypatch.setenv("LLM_BASEURL_2", "https://api.deepseek.com/v1")
    monkeypatch.setenv("LLM_API_KEY_2", "sk-deepseek-yyy")
    if models:
        for j, m in enumerate(models, 1):
            monkeypatch.setenv(f"LLM_MODELS_2_{j}", m)


# ── 配置解析测试 ──────────────────────────────


class TestConfigParsing:
    """编号制配置解析测试。"""

    def test_single_provider_fallback(self, monkeypatch):
        """未配置编号接口时，回退到单接口模式。"""
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-xxx")
        monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")

        from app.config import Settings

        s = Settings()
        providers = s.llm_providers
        assert len(providers) == 1
        assert providers[0]["base_url"] == "https://api.openai.com/v1"
        assert providers[0]["api_key"] == "sk-test-xxx"
        assert providers[0]["name"] == "openai"
        assert providers[0]["models"] == ["gpt-4o-mini"]

    def test_multi_provider_config(self, monkeypatch):
        """多接口配置正确解析，每个接口有独立的模型列表。"""
        _clear_llm_env(monkeypatch)
        _setup_provider_1(monkeypatch, models=["gpt-4o-mini", "gpt-4o"])
        _setup_provider_2(monkeypatch, models=["deepseek-chat", "deepseek-reasoner"])

        from app.config import Settings

        s = Settings()
        providers = s.llm_providers

        assert len(providers) == 2

        assert providers[0]["name"] == "provider-1"
        assert providers[0]["base_url"] == "https://api.openai.com/v1"
        assert providers[0]["api_key"] == "sk-openai-xxx"
        assert providers[0]["models"] == ["gpt-4o-mini", "gpt-4o"]

        assert providers[1]["name"] == "provider-2"
        assert providers[1]["base_url"] == "https://api.deepseek.com/v1"
        assert providers[1]["api_key"] == "sk-deepseek-yyy"
        assert providers[1]["models"] == ["deepseek-chat", "deepseek-reasoner"]

    def test_provider_with_single_model(self, monkeypatch):
        """接口只配置一个模型。"""
        _clear_llm_env(monkeypatch)
        _setup_provider_1(monkeypatch, models=["gpt-4o-mini"])

        from app.config import Settings

        s = Settings()
        providers = s.llm_providers
        assert len(providers) == 1
        assert providers[0]["models"] == ["gpt-4o-mini"]

    def test_no_providers_configured(self, monkeypatch):
        """未配置任何接口。"""
        _clear_llm_env(monkeypatch)

        from app.config import Settings

        s = Settings()
        providers = s.llm_providers
        assert providers == []

    def test_is_llm_enabled_with_numbered(self, monkeypatch):
        """编号接口配置后 is_llm_enabled 返回 True。"""
        _clear_llm_env(monkeypatch)
        _setup_provider_1(monkeypatch, models=["gpt-4o-mini"])
        monkeypatch.setenv("ENABLE_LLM_ENHANCEMENT", "true")

        from app.config import Settings

        s = Settings()
        assert s.is_llm_enabled is True


# ── 错误分类测试 ──────────────────────────────


class TestErrorClassification:
    def test_connection_error_is_connection(self):
        err = httpx.ConnectError("Connection refused")
        assert _is_connection_error(err) is True

    def test_timeout_is_connection(self):
        err = httpx.TimeoutException("timed out")
        assert _is_connection_error(err) is True

    def test_500_is_connection(self):
        resp = MagicMock()
        resp.status_code = 500
        resp.text = "Internal Server Error"
        err = httpx.HTTPStatusError("500", request=MagicMock(), response=resp)
        assert _is_connection_error(err) is True

    def test_429_is_connection(self):
        resp = MagicMock()
        resp.status_code = 429
        resp.text = "Too Many Requests"
        err = httpx.HTTPStatusError("429", request=MagicMock(), response=resp)
        assert _is_connection_error(err) is True

    def test_400_is_model_error(self):
        resp = MagicMock()
        resp.status_code = 400
        resp.text = "Bad Request: model not found"
        err = httpx.HTTPStatusError("400", request=MagicMock(), response=resp)
        assert _is_model_error(err) is True

    def test_404_is_model_error(self):
        resp = MagicMock()
        resp.status_code = 404
        resp.text = "Not Found"
        err = httpx.HTTPStatusError("404", request=MagicMock(), response=resp)
        assert _is_model_error(err) is True

    def test_200_is_neither(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "OK"
        err = httpx.HTTPStatusError("200", request=MagicMock(), response=resp)
        assert _is_connection_error(err) is False
        assert _is_model_error(err) is False


# ── 组合列表构建测试 ──────────────────────────


class TestCombinations:
    def test_2x2_combinations(self):
        providers = [
            LLMProvider(base_url="url1", api_key="key1", name="p1", models=["model-a", "model-b"]),
            LLMProvider(base_url="url2", api_key="key2", name="p2", models=["model-a", "model-b"]),
        ]
        combos = _build_combinations(providers)
        assert len(combos) == 4
        assert combos[0] == (providers[0], "model-a")
        assert combos[1] == (providers[0], "model-b")
        assert combos[2] == (providers[1], "model-a")
        assert combos[3] == (providers[1], "model-b")

    def test_different_models_per_provider(self):
        """每个接口有不同模型列表。"""
        providers = [
            LLMProvider(base_url="url1", api_key="key1", name="p1", models=["gpt-4o", "gpt-4o-mini"]),
            LLMProvider(base_url="url2", api_key="key2", name="p2", models=["deepseek-chat"]),
        ]
        combos = _build_combinations(providers)
        assert len(combos) == 3
        assert combos[0][1] == "gpt-4o"
        assert combos[1][1] == "gpt-4o-mini"
        assert combos[2][1] == "deepseek-chat"

    def test_1x3_combinations(self):
        providers = [
            LLMProvider(base_url="url1", api_key="key1", name="p1", models=["m1", "m2", "m3"]),
        ]
        combos = _build_combinations(providers)
        assert len(combos) == 3


# ── 故障转移集成测试 ──────────────────────────


class TestFailover:
    @pytest.mark.asyncio
    async def test_first_provider_success(self, monkeypatch):
        """第一个接口成功，不尝试第二个。"""
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["model-a", "model-b"],
                },
                {
                    "base_url": "https://api2.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["model-a", "model-b"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(**kwargs):
            return _completion("LLM response from provider 1")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "LLM response from provider 1"
        assert result.provider_used == "provider-1"
        assert result.model_used == "model-a"
        assert len(result.attempts) == 1

    @pytest.mark.asyncio
    async def test_connection_error_triggers_provider_switch(self, monkeypatch):
        """接口1连接失败 → 自动切换到接口2。"""
        mock_settings = _mock_settings(
            [
                {"base_url": "https://api1.com/v1", "api_key": "key1", "name": "provider-1", "models": ["model-a"]},
                {"base_url": "https://api2.com/v1", "api_key": "key2", "name": "provider-2", "models": ["model-a"]},
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(provider, model, **kwargs):
            if provider.name == "provider-1":
                raise httpx.ConnectError("Connection refused")
            return _completion("Response from provider 2")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "Response from provider 2"
        assert result.provider_used == "provider-2"
        assert result.model_used == "model-a"
        assert len(result.attempts) == 2

    @pytest.mark.asyncio
    async def test_model_error_triggers_model_switch(self, monkeypatch):
        """模型1调用失败 → 自动切换到模型2。"""
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["model-a", "model-b"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(provider, model, **kwargs):
            if model == "model-a":
                resp = MagicMock()
                resp.status_code = 404
                resp.text = "model not found"
                raise httpx.HTTPStatusError("404", request=MagicMock(), response=resp)
            return _completion("Response with model-b")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "Response with model-b"
        assert result.model_used == "model-b"
        assert len(result.attempts) == 2

    @pytest.mark.asyncio
    async def test_all_providers_fail(self, monkeypatch):
        """所有接口和模型都失败 → 返回 None。"""
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["model-a", "model-b"],
                },
                {
                    "base_url": "https://api2.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["model-a", "model-b"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(**kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert result.text is None
        assert result.provider_used is None
        assert len(result.attempts) >= 1

    @pytest.mark.asyncio
    async def test_no_providers_configured(self, monkeypatch):
        """未配置任何接口 → 返回 None。"""
        mock_settings = _mock_settings([])
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert result.text is None

    @pytest.mark.asyncio
    async def test_failover_chain_p1_conn_p2_model_p2_ok(self, monkeypatch):
        """完整故障转移链：接口1连接失败 → 接口2模型1失败 → 接口2模型2成功。"""
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["model-a", "model-b"],
                },
                {
                    "base_url": "https://api2.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["model-a", "model-b"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(provider, model, **kwargs):
            if provider.name == "provider-1":
                raise httpx.ConnectError("Connection refused")
            if model == "model-a":
                resp = MagicMock()
                resp.status_code = 400
                resp.text = "model not found"
                raise httpx.HTTPStatusError("400", request=MagicMock(), response=resp)
            return _completion("Success on provider-2+model-b")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "Success on provider-2+model-b"
        assert result.provider_used == "provider-2"
        assert result.model_used == "model-b"
