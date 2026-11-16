"""采集器 per-item 容错回归（2026-11-13 审查 P2-5）。

背景：多个采集器的循环 `for item in items: result.items.append(
self._build_discovery(item))` 对脏数据无防护 —— 一条畸形行（无法解析的
时间戳、缺失字段）抛异常后整轮采集 status=error，**已转好的 items 全部
丢弃**。telegram/farcaster 的"单通道失败只丢该批"是成熟模式，这里把同款
容错下沉到基类 `_build_items`。

契约：单条失败只丢该条（warning 日志），整轮照常 success/partial。
"""

from __future__ import annotations

import pytest

from app.collectors.base import CollectorResult, DataCollector, RawDiscovery


class _StubCollector(DataCollector):
    """_build_discovery 对带 boom 标记的条目抛异常的桩采集器。"""

    def __init__(self) -> None:
        super().__init__("stub", "Stub")

    @property
    def source_type(self) -> str:
        return "api"

    async def collect(self) -> CollectorResult:
        return CollectorResult(source_id="stub")

    def _build_discovery(self, item: dict) -> RawDiscovery | None:
        if item.get("boom"):
            raise ValueError("bad row: unparsable timestamp")
        if item.get("skip"):
            return None
        return RawDiscovery(
            source_id=self.source_id,
            raw_id=f"raw-{item.get('name', 'x')}",
            name=str(item.get("name", "x")),
            url=f"https://example.com/{item.get('name', 'x')}",
            sector="DeFi",
            stage="pre-token",
            raw_data=dict(item),
        )


@pytest.fixture
def collector() -> _StubCollector:
    return _StubCollector()


def test_single_bad_row_does_not_kill_the_round(collector: _StubCollector) -> None:
    result = CollectorResult(source_id="stub")
    built, failed = collector._build_items([{"name": "a"}, {"boom": 1, "name": "dirty"}, {"name": "b"}], result)

    assert (built, failed) == (2, 1)
    assert [d.name for d in result.items] == ["a", "b"], "单条脏数据不得丢弃其余已转好的条目"


def test_none_build_result_is_skipped_not_counted_as_built(collector: _StubCollector) -> None:
    result = CollectorResult(source_id="stub")
    built, failed = collector._build_items([{"skip": 1}, {"name": "a"}], result)

    assert (built, failed) == (1, 0)
    assert len(result.items) == 1


def test_all_bad_rows_reports_full_failure_count(collector: _StubCollector) -> None:
    result = CollectorResult(source_id="stub")
    built, failed = collector._build_items([{"boom": 1}, {"boom": 1}], result)

    assert (built, failed) == (0, 2)
    assert result.items == []


def test_empty_batch_is_noop(collector: _StubCollector) -> None:
    result = CollectorResult(source_id="stub")
    assert collector._build_items([], result) == (0, 0)


async def test_coingecko_survives_dirty_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """端到端：整条脏数据只丢该条，采集轮仍 success 且保留好条目。"""
    from app.collectors.coingecko import CoinGeckoCollector

    collector = CoinGeckoCollector()
    original_rate_limiter = collector.rate_limiter

    class _NoopLimiter:
        async def __aenter__(self) -> _NoopLimiter:
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

    collector.rate_limiter = _NoopLimiter()  # type: ignore[assignment]

    async def fake_fetch_markets() -> list[dict]:
        return [{"id": "ok-coin", "name": "Ok"}, {"id": "bad", "name": "Bad"}]

    monkeypatch.setattr(collector, "_fetch_markets", fake_fetch_markets)

    original_build = collector._build_discovery

    def build_with_one_dirty(coin: dict) -> RawDiscovery:
        if coin["id"] == "bad":
            raise ValueError("unparsable timestamp")
        return original_build(coin)

    monkeypatch.setattr(collector, "_build_discovery", build_with_one_dirty)

    try:
        result = await collector.collect()
        assert result.status == "success", f"单条脏数据拖垮整轮：{result.error_message}"
        assert [d.name for d in result.items] == ["Ok"]
        assert original_rate_limiter is not collector.rate_limiter  # fixture 卫生哨兵
    finally:
        collector.rate_limiter = original_rate_limiter
