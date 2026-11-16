"""统一重试策略测试。

所有采集器的 HTTP 请求都经过 ``DataCollector.request_with_retry``，
这里用 DefiLlama 作为代表验证三件事：

1. 网络错误后重试并恢复；
2. 重试次数耗尽时采集结果进入 error；
3. ``*_RETRY=0`` 时只发一次请求。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from app.collectors.defillama import DefiLlamaCollector
from app.config import settings

PROTOCOLS_URL = "https://api.llama.fi/protocols"


class _NoopRateLimiter:
    """跳过令牌桶等待，避免重试用例被 1 rps 拖慢。"""

    async def __aenter__(self) -> _NoopRateLimiter:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


@pytest.fixture
def collector(monkeypatch) -> DefiLlamaCollector:
    """GITHUB_RETRY 之外的任一源：DEFILLAMA_RETRY=2（总尝试 3 次），退避置 0。"""
    monkeypatch.setattr(settings, "defillama_retry", 2)
    instance = DefiLlamaCollector()
    instance.rate_limiter = _NoopRateLimiter()  # type: ignore[assignment]
    instance.RETRY_BASE_DELAY = 0.0
    return instance


@respx.mock
async def test_any_collector_recovers_after_network_error(collector: DefiLlamaCollector) -> None:
    route = respx.get(PROTOCOLS_URL).mock(side_effect=[httpx.ConnectError("connection reset"), Response(200, json=[])])

    protocols = await collector._fetch_protocols()

    assert protocols == []
    assert route.call_count == 2


@respx.mock
async def test_retry_exhaustion_sets_error_status(collector: DefiLlamaCollector) -> None:
    route = respx.get(PROTOCOLS_URL).mock(return_value=Response(503))

    result = await collector.collect()

    assert result.status == "error"
    assert result.error_message is not None
    assert "503" in result.error_message
    assert route.call_count == 3  # 1 次首发 + 2 次重试


@respx.mock
async def test_zero_retry_makes_single_attempt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "defillama_retry", 0)
    instance = DefiLlamaCollector()
    instance.rate_limiter = _NoopRateLimiter()  # type: ignore[assignment]
    route = respx.get(PROTOCOLS_URL).mock(return_value=Response(500))

    result = await instance.collect()

    assert result.status == "error"
    assert route.call_count == 1


# ── 退避抖动（2026-11-13 审查 P2-4 回归）────────────────────────
#
# 纯确定性退避（1s/2s/4s）在多任务同时失败时会把重试**同步化**——
# 所有源在同一秒齐射重试，把上游打成二次风暴。契约：网络退避加
# [0, 0.5d) 的均匀抖动；Retry-After 是上游明确指令，不抖动。


def _seeded_collector() -> DefiLlamaCollector:
    collector = DefiLlamaCollector()
    collector.RETRY_BASE_DELAY = 1.0
    collector.RETRY_MAX_DELAY = 60.0
    return collector


def test_backoff_has_jitter(monkeypatch) -> None:
    """网络退避必须过抖动：[d, d + 0.5d)。"""
    import random as random_mod

    import app.collectors.base as base_mod

    collector = _seeded_collector()
    captured: dict = {}

    def fake_uniform(low: float, high: float) -> float:
        captured["low"], captured["high"] = low, high
        return 0.5 * high  # 抖动取一半 → 1.0 + 0.25 = 1.25（非确定性基线 1.0）

    monkeypatch.setattr(random_mod, "uniform", fake_uniform)
    monkeypatch.setattr(base_mod.random, "uniform", fake_uniform)

    delay = collector._retry_delay(1, None)

    assert (captured["low"], captured["high"]) == (0.0, 0.5), "退避没有经过抖动采样"
    assert delay == pytest.approx(1.25), f"退避仍是确定性值 {delay}（未加抖动）"


def test_retry_after_is_not_jittered() -> None:
    """上游 Retry-After 是明确指令：取大后原样等待，不打折扣也不抖动。"""
    collector = _seeded_collector()
    assert collector._retry_delay(1, 30.0) == 30.0
    assert collector._retry_delay(3, 120.0) == 60.0  # 封顶 RETRY_MAX_DELAY
