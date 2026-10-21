"""Unit tests for RootDataCollector (no live network)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.collectors.rootdata import RootDataCollector


@pytest.fixture
def collector(monkeypatch):
    c = RootDataCollector()
    # 只跑一个查询词，避免 DEFAULT_QUERIES 重复返回同一批条目
    monkeypatch.setattr(RootDataCollector, "DEFAULT_QUERIES", ("testnet",))
    return c


class TestNonProjectFilter:
    """ser_inv 是项目 / 机构 / 人物混合搜索：只有 type=1 进发现列表（2026-10-08）。"""

    async def test_people_and_social_entries_dropped_before_detail_fetch(self, collector, monkeypatch):
        search = AsyncMock(
            return_value=[
                {"id": 1011, "name": "Metis", "type": 1, "one_liner": "Layer2 network"},
                {"id": 12143, "name": "Deirdre Connolly", "type": 3},
                {"id": 472, "name": "Complete Web3 Testnets for Airdrops", "type": 5},
            ]
        )
        get_item = AsyncMock(return_value=None)
        get_fac = AsyncMock(return_value=[])
        monkeypatch.setattr(collector, "_search", search)
        monkeypatch.setattr(collector, "_get_item", get_item)
        monkeypatch.setattr(collector, "_get_fac", get_fac)

        result = await collector.collect()

        assert [d.raw_data["name"] for d in result.items] == ["Metis"]
        # 非项目条目连详情都不拉：省 API 配额
        assert [c.args[0] for c in get_item.await_args_list] == [1011]
        assert [c.args[0] for c in get_fac.await_args_list] == [1011]

    async def test_entries_without_type_still_collected(self, collector, monkeypatch):
        monkeypatch.setattr(collector, "_search", AsyncMock(return_value=[{"id": 7, "name": "Nova Rollup"}]))
        monkeypatch.setattr(collector, "_get_item", AsyncMock(return_value=None))
        monkeypatch.setattr(collector, "_get_fac", AsyncMock(return_value=[]))

        result = await collector.collect()

        assert [d.raw_data["name"] for d in result.items] == ["Nova Rollup"]
