"""llm_providers 指纹缓存回归（2026-11-13 审查 P2-6）。

背景：`llm_providers` property 会在**每条日志**上被访问
（`redact._known_secrets()` 收集要脱敏的密钥值），而它每次都现读
os.environ（最多约 240 个 LLM 相关键）并重新解析 —— 每条日志 240 次
environ 查找 + 解析的成本被遗漏了。

契约：相关输入（LLM environ 键 + settings 的三个单接口字段）不变时
重复访问**不再重新解析**；任一输入变化立即失效（不能让测试里
monkeypatch settings 字段后拿到旧配置）。
"""

from __future__ import annotations

import pytest

from app.config import Settings


@pytest.fixture(autouse=True)
def _reset_provider_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """缓存是模块级全局 —— 测试间必须清零，否则上一用例的指纹会命中本用例。"""
    import app.config as config_mod

    monkeypatch.setattr(config_mod, "_LLM_PROVIDER_CACHE", None)
    monkeypatch.setattr(config_mod, "_LLM_PROVIDER_FINGERPRINT", None)
    yield


@pytest.fixture
def counting_resolve(monkeypatch: pytest.MonkeyPatch) -> dict[str, int]:
    """包装 Settings._resolve_llm_providers，统计真实解析次数。"""
    counter = {"n": 0}
    original = Settings._resolve_llm_providers

    def counting(self: Settings) -> list[dict]:
        counter["n"] += 1
        return original(self)

    monkeypatch.setattr(Settings, "_resolve_llm_providers", counting)
    return counter


def test_repeat_access_uses_cache(counting_resolve: dict[str, int]) -> None:
    settings = Settings()
    settings.llm_model = "gpt-4o-mini"

    _ = settings.llm_providers
    _ = settings.llm_providers
    _ = settings.llm_providers

    assert counting_resolve["n"] == 1, (
        f"重复访问重新解析了 {counting_resolve['n']} 次 —— 每条日志 240 次 environ 查找的成本回来了"
    )


def test_environ_change_invalidates_cache(counting_resolve: dict[str, int], monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings()
    _ = settings.llm_providers
    assert counting_resolve["n"] == 1

    # 提供完整三元组（key+base_url+model）：只设 key 会触发 incomplete 告警，
    # 告警日志 → redact → llm_providers 在缓存落位前再入多解析一次，
    # 那是冷路径的已知代价，不属于本契约的观测量。
    monkeypatch.setenv("OPENAI_API_KEY_1", "sk-test-new-key")
    monkeypatch.setenv("OPENAI_BASE_URL_1", "https://api.example.com/v1")
    monkeypatch.setenv("OPENAI_MODEL_1_1", "gpt-4o-mini")  # j 从 1 起（与解析器一致）
    _ = settings.llm_providers

    assert counting_resolve["n"] == 2, "environ 变化没有使缓存失效"


def test_settings_field_change_invalidates_cache(
    counting_resolve: dict[str, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """monkeypatch settings 字段（测试惯例）同样必须触发重解析。"""
    settings = Settings()
    settings.llm_model = "model-a"
    _ = settings.llm_providers
    assert counting_resolve["n"] == 1

    monkeypatch.setattr(settings, "openai_api_key", "sk-changed")
    _ = settings.llm_providers

    assert counting_resolve["n"] == 2, "settings 字段变化没有使缓存失效"


def test_cached_result_is_a_copy(counting_resolve: dict[str, int]) -> None:
    """调用方拿到的是副本：外部改动不得污染缓存。"""
    settings = Settings()
    first = settings.llm_providers
    for provider in first:
        provider["base_url"] = "tampered"
        provider["models"] = []

    second = settings.llm_providers
    for provider in second:
        assert provider.get("base_url") != "tampered"
        assert provider.get("models") != []
