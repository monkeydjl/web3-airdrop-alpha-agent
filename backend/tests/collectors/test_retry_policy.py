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
