"""多接口多模型 LLM 客户端：配置迁移、组合轮询、故障转移（ADR-016）。

配置格式（新编号制优先，每个接口一组变量）：
    OPENAI_BASE_URL_1=https://api.openai.com/v1
    OPENAI_API_KEY_1=<key>
    OPENAI_MODEL_1_1=gpt-4o-mini
    OPENAI_MODEL_1_2=gpt-4o

旧编号格式 `LLM_BASEURL_N` / `LLM_API_KEY_N` / `LLM_MODELS_N_M` 在弃用窗口内
仍支持，新旧同时存在时新格式优先。

**轮询状态是模块级的**，所以每个用例前都要复位指针（见 `_reset_rr`）——
否则「第 1 次调用应命中 provider-1」这类断言会取决于同文件里前面跑了几个
用例，而那种失败在本地与 CI 上表现不同（收集顺序、`-k` 过滤都会改变它）。
"""

import asyncio
from unittest.mock import MagicMock

import httpx
import pytest

from app.llm.client import (
    LLMProvider,
    _build_combinations,
    _is_connection_error,
    _is_model_error,
    _RawCompletion,
    _reset_round_robin_for_tests,
    _rotate,
    llm_chat,
)


@pytest.fixture(autouse=True)
def _reset_rr():
    """每个用例都从轮询起点开始。autouse —— 漏加一次就引入顺序依赖。"""
    _reset_round_robin_for_tests()
    yield
    _reset_round_robin_for_tests()


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
    """清除**两套**编号变量 + 单接口变量。

    清理范围必须覆盖 config.py 的实际扫描上限。只清到 5 的话，
    环境里残留的 `OPENAI_API_KEY_6` 会让「未配置任何接口」这类用例意外拿到
    一个 provider —— 而失败信息会指向业务逻辑，不指向没清干净的环境。

    **范围直接从被测常量取**，不写字面量 10：以后把上限调到 20 时，
    硬编码的清理范围不会跟着走，于是 11~20 号残留变量开始污染用例，
    而红出来的会是别的断言。
    """
    from app.config import _LLM_MAX_MODELS_PER_PROVIDER, _LLM_MAX_PROVIDERS

    for i in range(1, _LLM_MAX_PROVIDERS + 1):
        for key in (
            f"OPENAI_BASE_URL_{i}",
            f"OPENAI_API_KEY_{i}",
            f"LLM_BASEURL_{i}",
            f"LLM_API_KEY_{i}",
        ):
            monkeypatch.delenv(key, raising=False)
        for j in range(1, _LLM_MAX_MODELS_PER_PROVIDER + 1):
            monkeypatch.delenv(f"OPENAI_MODEL_{i}_{j}", raising=False)
            monkeypatch.delenv(f"LLM_MODELS_{i}_{j}", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("LLM_MODEL", "gpt-4o-mini")


def _setup_provider_1(monkeypatch, models=None, *, legacy: bool = False):
    """配置接口 1。`legacy=True` 时用旧变量名，用于迁移兼容测试。"""
    if legacy:
        monkeypatch.setenv("LLM_BASEURL_1", "https://api.openai.com/v1")
        monkeypatch.setenv("LLM_API_KEY_1", "legacy-key-provider-1")
        for j, m in enumerate(models or [], 1):
            monkeypatch.setenv(f"LLM_MODELS_1_{j}", m)
        return
    monkeypatch.setenv("OPENAI_BASE_URL_1", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY_1", "test-key-provider-1")
    for j, m in enumerate(models or [], 1):
        monkeypatch.setenv(f"OPENAI_MODEL_1_{j}", m)


def _setup_provider_2(monkeypatch, models=None, *, legacy: bool = False):
    """配置接口 2。"""
    if legacy:
        monkeypatch.setenv("LLM_BASEURL_2", "https://api.deepseek.com/v1")
        monkeypatch.setenv("LLM_API_KEY_2", "legacy-key-provider-2")
        for j, m in enumerate(models or [], 1):
            monkeypatch.setenv(f"LLM_MODELS_2_{j}", m)
        return
    monkeypatch.setenv("OPENAI_BASE_URL_2", "https://api.deepseek.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY_2", "test-key-provider-2")
    for j, m in enumerate(models or [], 1):
        monkeypatch.setenv(f"OPENAI_MODEL_2_{j}", m)


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
        assert providers[0]["api_key"] == "test-key-provider-1"
        assert providers[0]["models"] == ["gpt-4o-mini", "gpt-4o"]

        assert providers[1]["name"] == "provider-2"
        assert providers[1]["base_url"] == "https://api.deepseek.com/v1"
        assert providers[1]["api_key"] == "test-key-provider-2"
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


# ── 新旧编号格式迁移（ADR-016 §1）─────────────


class TestNumberedConfigMigration:
    """`OPENAI_*_N` 优先、旧 `LLM_*_N` 兼容、两者不合并。"""

    def test_new_style_numbered_config_is_parsed(self, monkeypatch):
        """新格式 OPENAI_BASE_URL_N / OPENAI_API_KEY_N / OPENAI_MODEL_N_M 生效。

        这是本次改造的原始诉求：owner 手上的模板就是这个写法，
        改造前照它填**一个接口都不会注册且不报错**。
        """
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://openrouter.ai/api/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "router-key-1")
        monkeypatch.setenv("OPENAI_MODEL_1_1", "minimax/minimax-m3:free")
        monkeypatch.setenv("OPENAI_MODEL_1_2", "nvidia/nemotron-3-ultra:free")

        from app.config import Settings

        providers = Settings().llm_providers
        assert len(providers) == 1
        assert providers[0]["base_url"] == "https://openrouter.ai/api/v1"
        assert providers[0]["api_key"] == "router-key-1"
        assert providers[0]["models"] == [
            "minimax/minimax-m3:free",
            "nvidia/nemotron-3-ultra:free",
        ]

    def test_legacy_numbered_config_still_works(self, monkeypatch):
        """旧格式在弃用窗口内仍生效 —— 已有部署升级后不能静默失效。"""
        _clear_llm_env(monkeypatch)
        _setup_provider_1(monkeypatch, models=["gpt-4o-mini"], legacy=True)

        from app.config import Settings

        providers = Settings().llm_providers
        assert len(providers) == 1
        assert providers[0]["api_key"] == "legacy-key-provider-1"

    def test_new_style_wins_over_legacy_without_merging(self, monkeypatch):
        """新旧同时存在时取新格式，且**不合并**。

        合并的语义无法向运维解释：「2 个新 + 2 个旧 = 4 个接口，轮询顺序是
        什么」没有正确答案。更实际的风险是「旧配置忘删」静默变成额外的
        付费接口 —— 账单上才发现。
        """
        _clear_llm_env(monkeypatch)
        _setup_provider_1(monkeypatch, models=["new-model"])
        _setup_provider_2(monkeypatch, models=["legacy-model"], legacy=True)

        from app.config import Settings

        providers = Settings().llm_providers
        assert len(providers) == 1, "新旧格式被合并了 —— 轮询顺序将无法解释"
        assert providers[0]["models"] == ["new-model"]
        assert all(p["api_key"] != "legacy-key-provider-2" for p in providers)

    def test_numbering_gaps_do_not_truncate(self, monkeypatch):
        """编号有空洞时后面的接口仍被读到。

        注释掉中间某个接口是很自然的运维操作，「遇到空洞就停」会静默丢掉
        它后面的**全部**接口。
        """
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-a")
        monkeypatch.setenv("OPENAI_MODEL_1_1", "model-a")
        # 故意跳过 2
        monkeypatch.setenv("OPENAI_BASE_URL_3", "https://c.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_3", "key-c")
        monkeypatch.setenv("OPENAI_MODEL_3_1", "model-c")

        from app.config import Settings

        providers = Settings().llm_providers
        assert [p["name"] for p in providers] == ["provider-1", "provider-3"]

    def test_sixth_provider_is_not_silently_dropped(self, monkeypatch):
        """第 6 个接口必须被读到 —— 旧实现的上限是 5，第 6 个静默消失。

        owner 的实际配置就是 6 个接口。「配了但状态接口只显示 5 个」
        属于最难自查的一类：没有报错，只是少一个。
        """
        _clear_llm_env(monkeypatch)
        for i in range(1, 7):
            monkeypatch.setenv(f"OPENAI_BASE_URL_{i}", f"https://p{i}.example.com/v1")
            monkeypatch.setenv(f"OPENAI_API_KEY_{i}", f"key-{i}")
            monkeypatch.setenv(f"OPENAI_MODEL_{i}_1", f"model-{i}")

        from app.config import Settings

        providers = Settings().llm_providers
        assert len(providers) == 6
        assert providers[-1]["name"] == "provider-6"


class TestProviderValidity:
    """「配置了」必须等于「可调用」（ADR-016 §2）。"""

    def test_provider_without_models_is_skipped(self, monkeypatch):
        """配了 base_url + key 但没配模型 → 不是有效接口。

        旧实现会把它注册进来，于是候选组合数是 0 而 provider_count 是 1 ——
        状态接口显示"有一个接口"，实际每次调用都无候选可试。
        """
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-a")

        from app.config import Settings

        assert Settings().llm_providers == []

    def test_provider_without_api_key_is_skipped(self, monkeypatch):
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_MODEL_1_1", "model-a")

        from app.config import Settings

        assert Settings().llm_providers == []

    def test_glued_base_url_line_is_rejected(self, monkeypatch):
        """base_url 不是 http(s):// 开头就拒绝。

        真实踩到的形态是复制模板时两行粘成一行：

            OPENAI_BASE_URL_2=OPENAI_MODEL_2_1=agnes-2.5-flash

        不校验的话整个右侧会被当成 base_url，直到**第一次真实调用**才失败，
        而且报的是连接错误 —— 把排查方向指向网络而不是配置。
        """
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_2", "OPENAI_MODEL_2_1=agnes-2.5-flash")
        monkeypatch.setenv("OPENAI_API_KEY_2", "key-b")
        monkeypatch.setenv("OPENAI_MODEL_2_1", "agnes-2.5-flash")

        from app.config import Settings

        assert Settings().llm_providers == []

    def test_valid_providers_survive_alongside_invalid_ones(self, monkeypatch):
        """一个半配置的接口不能带走其它有效接口。"""
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://good.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-good")
        monkeypatch.setenv("OPENAI_MODEL_1_1", "model-good")
        monkeypatch.setenv("OPENAI_BASE_URL_2", "https://bad.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_2", "key-bad")  # 缺模型

        from app.config import Settings

        providers = Settings().llm_providers
        assert [p["name"] for p in providers] == ["provider-1"]

    def test_is_llm_enabled_false_when_key_present_but_no_model(self, monkeypatch):
        """有 key 没模型 → `is_llm_enabled` 必须是 False。

        旧实现只查「某个编号 KEY 是否非空」，于是这种配置得到
        `enabled=True` + 零候选：状态接口说启用了，每次调用静默走规则引擎。
        """
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("ENABLE_LLM_ENHANCEMENT", "true")
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-a")

        from app.config import Settings

        assert Settings().is_llm_enabled is False

    def test_is_llm_enabled_false_when_flag_off(self, monkeypatch):
        """Feature Flag 关着时，配得再全也不启用（ADR-001）。"""
        _clear_llm_env(monkeypatch)
        monkeypatch.setenv("ENABLE_LLM_ENHANCEMENT", "false")
        _setup_provider_1(monkeypatch, models=["model-a"])

        from app.config import Settings

        assert Settings().is_llm_enabled is False


class TestConfigWarningsDoNotRecurse:
    """从 provider 解析里写日志会成环 —— 这是实测踩到的 RecursionError。

    链路：`llm_providers` → `logger.warning` → 日志 processor
    → `redact._known_secrets()` → `settings.llm_providers` → `logger.warning` → …

    脱敏 processor 为了知道"哪些字符串是密钥"必须读 provider 列表，
    所以这个环是结构性的，不是某处写错。
    """

    def test_incomplete_provider_warning_does_not_recurse(self, monkeypatch):
        """半配置接口的告警必须能安全发出，且不会递归爆栈。"""
        from app.config import Settings, _reset_llm_config_warnings_for_tests

        _clear_llm_env(monkeypatch)
        _reset_llm_config_warnings_for_tests()
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-a")  # 缺模型

        s = Settings()
        # 反复访问：既验证不递归，也验证不会每次都重复刷告警
        assert s.llm_providers == []
        assert s.llm_providers == []

    def test_warning_is_emitted_once_per_fingerprint(self, monkeypatch):
        """同一条配置问题只告警一次。

        这个 property 会在**每条日志记录**上被访问（脱敏要读它），不去重的话
        一条告警会跟着全部日志量一起翻倍输出，把日志淹掉。

        同时这条也钉住「去重不能把**第一条**也吞掉」—— 那正是本次要修的
        静默失效本身。用深度计数而不是布尔标志就是为了这个。
        """
        import structlog

        from app.config import Settings, _reset_llm_config_warnings_for_tests

        _clear_llm_env(monkeypatch)
        _reset_llm_config_warnings_for_tests()
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "key-a")  # 缺模型

        s = Settings()
        with structlog.testing.capture_logs() as logs:
            # 三次都必须得到同样的空结果 —— 去重不能顺手把解析结果也缓存歪
            assert s.llm_providers == []
            assert s.llm_providers == []
            assert s.llm_providers == []

        hits = [e for e in logs if e.get("event") == "llm.provider_config_incomplete"]
        assert len(hits) == 1, f"告警发了 {len(hits)} 次，应恰好 1 次：{hits}"
        assert hits[0]["missing"] == "models"
        assert hits[0]["index"] == 1

    def test_warning_fields_never_carry_the_api_key(self, monkeypatch):
        """告警字段里**绝不能**出现密钥值 —— 日志会落文件、可能被集中采集。"""
        import structlog

        from app.config import Settings, _reset_llm_config_warnings_for_tests

        _clear_llm_env(monkeypatch)
        _reset_llm_config_warnings_for_tests()
        secret = "super-secret-key-value-98765"
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://a.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", secret)  # 缺模型 → 触发告警

        s = Settings()
        with structlog.testing.capture_logs() as logs:
            assert s.llm_providers == []

        assert secret not in repr(logs), "配置告警把密钥值写进了日志"

    def test_legacy_ignored_warning_is_emitted(self, monkeypatch):
        """新旧混用时必须有告警 —— 否则旧变量残留会让人改错地方。"""
        import structlog

        from app.config import Settings, _reset_llm_config_warnings_for_tests

        _clear_llm_env(monkeypatch)
        _reset_llm_config_warnings_for_tests()
        _setup_provider_1(monkeypatch, models=["new-model"])
        _setup_provider_2(monkeypatch, models=["legacy-model"], legacy=True)

        s = Settings()
        with structlog.testing.capture_logs() as logs:
            # 新格式胜出：只有 provider-1，旧编号被忽略
            assert [p["name"] for p in s.llm_providers] == ["provider-1"]

        events = [e["event"] for e in logs]
        assert "llm.legacy_numbered_config_ignored" in events


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


class TestRotate:
    """旋转必须**保序且不丢项** —— 它决定 failover 深度。"""

    def test_rotation_preserves_all_items(self):
        combos = [("p", f"m{i}") for i in range(4)]
        for start in range(6):
            rotated = _rotate(combos, start)
            assert len(rotated) == len(combos), "旋转丢了组合 —— failover 深度会随请求序号变化"
            assert set(rotated) == set(combos)

    def test_rotation_starts_at_index(self):
        combos = [("p", f"m{i}") for i in range(4)]
        assert _rotate(combos, 2) == [("p", "m2"), ("p", "m3"), ("p", "m0"), ("p", "m1")]

    def test_rotation_wraps_out_of_range_index(self):
        combos = [("p", "m0"), ("p", "m1")]
        assert _rotate(combos, 5) == [("p", "m1"), ("p", "m0")]

    def test_rotation_of_empty_list(self):
        assert _rotate([], 3) == []


# ── 组合级轮询（ADR-016 §3）───────────────────


def _rr_settings():
    """2 接口 × 2 模型 = 4 个候选组合，用于观察轮询推进。"""
    return _mock_settings(
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
                "models": ["model-c", "model-d"],
            },
        ]
    )


class TestRoundRobin:
    """连续调用必须**轮换起点**，而不是每次都从第一个组合开始。"""

    @pytest.mark.asyncio
    async def test_successive_calls_advance_through_all_combinations(self, monkeypatch):
        """4 个组合、4 次调用 → 每个组合各被用作起点一次。

        这是本次改造的核心断言。改造前 4 次调用会全部落在
        provider-1/model-a 上 —— 配了 4 个组合只有 1 个在承担流量。
        """
        monkeypatch.setattr("app.llm.client.settings", _rr_settings())

        async def mock_try_single(**kwargs):
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        used = []
        for _ in range(4):
            r = await llm_chat(messages=[{"role": "user", "content": "hi"}])
            used.append((r.provider_used, r.model_used))

        assert used == [
            ("provider-1", "model-a"),
            ("provider-1", "model-b"),
            ("provider-2", "model-c"),
            ("provider-2", "model-d"),
        ]

    @pytest.mark.asyncio
    async def test_pointer_wraps_after_a_full_cycle(self, monkeypatch):
        """走完一轮回到第一个组合，而不是停在末尾或越界。"""
        monkeypatch.setattr("app.llm.client.settings", _rr_settings())

        async def mock_try_single(**kwargs):
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        used = []
        for _ in range(5):
            r = await llm_chat(messages=[{"role": "user", "content": "hi"}])
            used.append((r.provider_used, r.model_used))

        assert used[4] == used[0] == ("provider-1", "model-a")

    @pytest.mark.asyncio
    async def test_pointer_advances_even_when_the_call_fails(self, monkeypatch):
        """失败也要推进指针。

        若只在成功后推进，一个持续失败的组合会被每次调用都当作起点重试 ——
        轮询退化回固定顺序，还额外付出全部失败组合的超时。
        """
        monkeypatch.setattr("app.llm.client.settings", _rr_settings())

        async def always_fail(**kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("app.llm.client._try_single", always_fail)
        r1 = await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert r1.ok is False
        assert r1.attempts[0].provider == "provider-1"

        async def ok(**kwargs):
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", ok)
        r2 = await llm_chat(messages=[{"role": "user", "content": "hi"}])
        assert (r2.provider_used, r2.model_used) == ("provider-1", "model-b"), (
            "第一次调用失败后指针没有推进 —— 轮询退化成了固定顺序"
        )

    @pytest.mark.asyncio
    async def test_rotation_still_tries_every_combination_on_failure(self, monkeypatch):
        """从第 3 个组合起步时，仍然会试完全部 4 个（环绕回头）。

        旋转而不是截断的意义就在这里：failover 深度不能随请求序号变化，
        否则「第几次调用」会决定「能不能降级成功」—— 可用性变成掷骰子。
        """
        monkeypatch.setattr("app.llm.client.settings", _rr_settings())

        async def ok(**kwargs):
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", ok)
        # 消耗掉 2 次，让指针指向第 3 个组合
        await llm_chat(messages=[{"role": "user", "content": "hi"}])
        await llm_chat(messages=[{"role": "user", "content": "hi"}])

        tried: list[tuple[str, str]] = []

        async def record_and_fail(provider, model, **kwargs):
            tried.append((provider.name, model))
            raise httpx.HTTPStatusError("400", request=MagicMock(), response=_model_err_resp())

        monkeypatch.setattr("app.llm.client._try_single", record_and_fail)
        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert tried == [
            ("provider-2", "model-c"),
            ("provider-2", "model-d"),
            ("provider-1", "model-a"),
            ("provider-1", "model-b"),
        ]

    @pytest.mark.asyncio
    async def test_concurrent_calls_get_distinct_start_points(self, monkeypatch):
        """并发调用不能拿到同一个起点。

        `llm_chat` 本来就会被并发调用（LLM_SEMAPHORE_SIZE 默认 5）。
        起点重复意味着并发流量全砸在同一个接口上 —— 正是轮询要解决的问题。
        """
        monkeypatch.setattr("app.llm.client.settings", _rr_settings())

        async def slow_ok(**kwargs):
            await asyncio.sleep(0)
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", slow_ok)

        results = await asyncio.gather(*(llm_chat(messages=[{"role": "user", "content": "hi"}]) for _ in range(4)))
        starts = {(r.provider_used, r.model_used) for r in results}
        assert len(starts) == 4, f"并发调用起点重复：{starts}"

    @pytest.mark.asyncio
    async def test_single_combination_config_is_stable(self, monkeypatch):
        """只有 1 个组合时，轮询不能把它取模成越界或跳过。"""
        monkeypatch.setattr(
            "app.llm.client.settings",
            _mock_settings(
                [{"base_url": "https://a.com/v1", "api_key": "k", "name": "provider-1", "models": ["only"]}]
            ),
        )

        async def ok(**kwargs):
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", ok)
        for _ in range(3):
            r = await llm_chat(messages=[{"role": "user", "content": "hi"}])
            assert (r.provider_used, r.model_used) == ("provider-1", "only")


def _model_err_resp():
    resp = MagicMock()
    resp.status_code = 400
    resp.text = "model not found"
    return resp


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
    async def test_connection_error_skips_remaining_models_of_that_provider(self, monkeypatch):
        """连接级失败必须跳过该接口的**剩余模型**，而不是逐个重试。

        接口连不上是接口的问题，换一个模型名再连同一个地址不会有别的结果，
        只会再付一个连接超时（默认 10s）。

        **这是回归测试**：原实现写的是「重建 combinations 列表」——

            remaining = [c for c in combinations[len(attempts):] if c[0] != provider]
            combinations = combinations[:len(attempts)] + remaining

        `for x in combinations` 在进入循环时就取好了迭代器，之后把
        `combinations` 这个**名字**指向新列表完全不影响正在进行的迭代，
        所以那段跳过逻辑是**死代码**。它一直没被测出来是因为既有用例里每个
        provider 只配 1 个模型 —— 「跳过剩余模型」和「没有剩余模型」看起来
        一样。这里刻意给每个 provider 配 3 个模型把差别暴露出来。
        """
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://dead.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["m1", "m2", "m3"],
                },
                {
                    "base_url": "https://alive.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["m1", "m2", "m3"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        tried: list[tuple[str, str]] = []

        async def mock_try_single(provider, model, **kwargs):
            tried.append((provider.name, model))
            if provider.name == "provider-1":
                raise httpx.ConnectError("Connection refused")
            return _completion("ok from provider-2")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.provider_used == "provider-2"
        assert tried == [("provider-1", "m1"), ("provider-2", "m1")], (
            f"挂掉的接口被逐个模型重试了：{tried}。6 接口 × 3 模型的配置下这会把一次降级从 10s 拖到 30s。"
        )

    @pytest.mark.asyncio
    async def test_model_error_stays_on_the_same_provider(self, monkeypatch):
        """模型级失败只跳当前模型 —— 不能连带把整个接口判死。

        与上一条互为反向约束：如果实现把两类错误混为一谈（都跳接口），
        一个模型名写错就会浪费掉该接口下其余可用的模型。
        """
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["bad-name", "good-name"],
                },
                {
                    "base_url": "https://api2.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["m1"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(provider, model, **kwargs):
            if model == "bad-name":
                raise httpx.HTTPStatusError("404", request=MagicMock(), response=_model_err_resp())
            return _completion("ok")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.provider_used == "provider-1", "模型名错误把整个接口判死了"
        assert result.model_used == "good-name"

    @pytest.mark.asyncio
    async def test_will_retry_is_false_on_the_last_real_attempt(self, monkeypatch):
        """`will_retry` 必须反映**真的还会不会再试**，不能只比计数。

        原写法 `len(attempts) < len(combinations)` 有两处失真：
          1. 被跳过的组合不进 `attempts`，计数与下标脱钩；
          2. 连接失败让本 provider 剩余模型全部作废，拿总数比较只会朝
             「还有兜底」的方向错报。

        这里的场景恰好同时踩中两点：provider-1 有 3 个模型，第一次调用就
        连接失败 → 剩余 2 个作废、provider-2 是唯一后续。等到 provider-2
        也失败时 `len(attempts)` 只有 2、`len(combinations)` 是 4，
        旧写法会报 True，而实际上函数紧接着就返回了 `text=None`。

        字段错报的代价是排查方向被带偏：日志说「还会重试」而结果是降级，
        人会去查「重试为什么没生效」这个根本不存在的问题。
        """
        import structlog

        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://dead.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["m1", "m2", "m3"],
                },
                {
                    "base_url": "https://also-dead.com/v1",
                    "api_key": "key2",
                    "name": "provider-2",
                    "models": ["m1"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(provider, model, **kwargs):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        with structlog.testing.capture_logs() as logs:
            result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.text is None
        failures = [e for e in logs if e.get("event") == "llm.attempt_failed"]
        assert [e["provider"] for e in failures] == ["provider-1", "provider-2"], (
            f"跳过逻辑没生效，实际尝试：{[(e['provider'], e['model']) for e in failures]}"
        )
        assert failures[0]["will_retry"] is True, "provider-2 还没试就报不再重试了"
        assert failures[-1]["will_retry"] is False, "最后一次失败仍报 will_retry=True，但函数紧接着就返回了 None"

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


# ── 输出泄漏过滤（SECURITY §10.5）─────────────────


class TestDetectSecretLeak:
    """`detect_secret_leak` 单元测试：已知密钥值 + 通用 pattern 两类都有覆盖。"""

    def test_known_secret_value_hit(self, monkeypatch):
        from app.utils.redact import detect_secret_leak

        monkeypatch.setattr(
            "app.utils.redact._known_secrets",
            lambda: ["my-super-secret-value-12345"],
        )
        # 首尾加普通文本，确认是子串匹配而非全等匹配
        assert detect_secret_leak("结论：my-super-secret-value-12345 是密钥") == "known_secret_value"

    def test_generic_openai_key_pattern(self):
        from app.utils.redact import detect_secret_leak

        assert detect_secret_leak("key is sk-abcdefghijklmnopqrstuvwxyz123456") == "openai_key"

    def test_generic_github_pat_pattern(self):
        from app.utils.redact import detect_secret_leak

        assert detect_secret_leak("token ghp_abcdefghijklmnopqrstuvwxyz1234567890") == "github_pat"

    def test_clean_text_returns_none(self):
        from app.utils.redact import detect_secret_leak

        assert detect_secret_leak("FARM：社区热度高，建议参与") is None
        assert detect_secret_leak("") is None
        assert detect_secret_leak("short sk-abc") is None  # 长度不足，不误报

    def test_bearer_token_pattern(self):
        from app.utils.redact import detect_secret_leak

        assert detect_secret_leak("Authorization: Bearer abcdefghijklmnopqrstuvwxyz123456") == "bearer_token"

    def test_new_source_secrets_and_llm_provider_keys_are_known(self, monkeypatch):
        """P2 源的密钥 + 自建 LLM 代理的 Key 必须进「已知密钥值」集合。

        这些值不靠字段名规则、也不靠 sk-/ghp_ 通用 pattern（自建代理 Key 常
        不是这些形状），只能靠值匹配抓 —— 漏进集合就会两头漏。
        """
        from app.config import settings as real_settings
        from app.utils.redact import _known_secrets

        monkeypatch.setattr(real_settings, "discord_bot_token", "discord-secret-value-123")
        monkeypatch.setattr(real_settings, "reddit_client_secret", "reddit-secret-value-456")
        # llm_providers 是只读 property，由编号环境变量现读，不能 setattr ——
        # 直接喂环境变量让它推导出自建代理 Key。
        # ⚠️ 必须配齐 base_url + key + **模型**：ADR-016 起半配置的接口不再
        # 注册，只喂前两个的话 llm_providers 是空列表，这条断言会以
        # 「密钥没进集合」的形式失败，而真实原因是配置不完整。
        monkeypatch.setenv("OPENAI_BASE_URL_1", "https://custom.example.com/v1")
        monkeypatch.setenv("OPENAI_API_KEY_1", "custom-llm-key-789")
        monkeypatch.setenv("OPENAI_MODEL_1_1", "custom-model")

        secrets = _known_secrets()
        assert "discord-secret-value-123" in secrets
        assert "reddit-secret-value-456" in secrets
        assert "custom-llm-key-789" in secrets


class TestSecretLeakDiscard:
    """`llm_chat` 集成测试：输出含密钥 pattern 时丢弃结果、不重试。"""

    @pytest.mark.asyncio
    async def test_secret_pattern_output_is_discarded(self, monkeypatch):
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

        # 输出里夹了一个 OpenAI key 形状的字符串
        async def mock_try_single(**kwargs):
            return _completion("结论：FARM。secret=sk-abcdefghijklmnopqrstuvwxyz123456")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is False
        assert result.text is None
        assert result.leak_detected is True
        # 丢弃不应重试其余组合：泄漏是内容问题，不是接口问题
        assert len(result.attempts) == 1

    @pytest.mark.asyncio
    async def test_clean_output_is_not_discarded(self, monkeypatch):
        mock_settings = _mock_settings(
            [
                {
                    "base_url": "https://api1.com/v1",
                    "api_key": "key1",
                    "name": "provider-1",
                    "models": ["model-a"],
                },
            ]
        )
        monkeypatch.setattr("app.llm.client.settings", mock_settings)

        async def mock_try_single(**kwargs):
            return _completion("FARM：社区热度高，规则引擎可离线复现")

        monkeypatch.setattr("app.llm.client._try_single", mock_try_single)

        result = await llm_chat(messages=[{"role": "user", "content": "hi"}])

        assert result.ok is True
        assert result.text == "FARM：社区热度高，规则引擎可离线复现"
        assert result.leak_detected is False
