"""Tests for the Galxe quest collector."""

import json

import httpx
import pytest
import respx
from httpx import Response

from app.collectors.galxe import GalxeCollector
from app.config import settings


@pytest.fixture
def galxe_enabled(monkeypatch):
    """启用 Galxe 并配置测试 API key。"""
    monkeypatch.setattr(settings, "galxe_enabled", True)
    monkeypatch.setattr(settings, "galxe_api_key", "test_galxe_key")


class TestGalxeCollector:
    def test_disabled_without_flag(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "galxe_enabled", False)
        monkeypatch.setattr(settings, "galxe_api_key", "key")
        collector = GalxeCollector()
        assert not collector.is_enabled()

    def test_disabled_without_key(self, monkeypatch) -> None:
        monkeypatch.setattr(settings, "galxe_enabled", True)
        monkeypatch.setattr(settings, "galxe_api_key", "")
        collector = GalxeCollector()
        assert not collector.is_enabled()

    @respx.mock
    async def test_collect_active_token_campaign(self, galxe_enabled) -> None:
        # 2026-11-16：生产 schema 下线 campaignList，迁移到 campaigns 连接
        # （Relay 式 first/after 分页，生产端点内省确认）。
        payload = {
            "data": {
                "campaigns": {
                    "totalCount": 1,
                    "list": [
                        {
                            "id": "gc123",
                            "name": "NovaLayer Early Adopters",
                            "description": "Join the testnet and earn tokens",
                            "status": "ACTIVE",
                            "rewardType": "TOKEN",
                            "thumbnail": "https://example.com/thumb.png",
                            "space": {"id": "sp1", "name": "NovaLayer", "alias": "novalayer"},
                        }
                    ],
                    "pageInfo": {"hasNextPage": False, "endCursor": None},
                }
            }
        }
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(200, json=payload)

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "success"
        assert len(result.items) == 1
        discovery = result.items[0]
        assert discovery.name == "NovaLayer"
        # 同 layer3：不臆造赛道，留空由合并阶段按名称归并
        assert discovery.sector is None
        assert discovery.discovery_score > 0.5

    @respx.mock
    async def test_collect_graphql_error(self, galxe_enabled) -> None:
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(
            200, json={"errors": [{"message": "unauthorized"}]}
        )

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "error"
        assert "unauthorized" in result.error_message

    @respx.mock
    async def test_collect_empty_list(self, galxe_enabled) -> None:
        respx.post("https://graphigo.prd.galaxy.eco/query").return_value = Response(
            200, json={"data": {"campaigns": {"totalCount": 0, "list": [], "pageInfo": {"hasNextPage": False}}}}
        )

        collector = GalxeCollector()
        result = await collector.collect()
        assert result.status == "partial"
        assert result.items == []

    @respx.mock
    async def test_collect_follows_end_cursor(self, galxe_enabled) -> None:
        """pageInfo.endCursor 存在时跟随翻页（封顶 MAX_CURSOR_PAGES）。"""
        payloads = [
            {
                "data": {
                    "campaigns": {
                        "totalCount": 2,
                        "list": [
                            {
                                "id": "gc1",
                                "name": "NovaLayer Early Adopters",
                                "status": "ACTIVE",
                                "rewardType": "TOKEN",
                                "space": {"id": "sp1", "name": "NovaLayer", "alias": "novalayer"},
                            }
                        ],
                        "pageInfo": {"hasNextPage": True, "endCursor": "cur-2"},
                    }
                }
            },
            {
                "data": {
                    "campaigns": {
                        "totalCount": 2,
                        "list": [
                            {
                                "id": "gc2",
                                "name": "Beta Campaign",
                                "status": "ACTIVE",
                                "rewardType": "OAT",
                                "space": {"id": "sp1", "name": "NovaLayer", "alias": "novalayer"},
                            }
                        ],
                        "pageInfo": {"hasNextPage": False, "endCursor": None},
                    }
                }
            },
        ]
        calls: list[str] = []

        def _page(request: httpx.Request) -> Response:
            body = json.loads(request.content.decode("utf-8"))
            calls.append((body.get("variables") or {}).get("after"))
            return Response(200, json=payloads[len(calls) - 1])

        respx.post("https://graphigo.prd.galaxy.eco/query").mock(side_effect=_page)

        collector = GalxeCollector()
        result = await collector.collect()

        assert result.status == "success"
        assert [d.raw_id for d in result.items] == ["gc1", "gc2"], "第二页 campaign 被丢弃"
        # 第一次 after 为 None（variables 里显式传 null），第二次为 cur-2
        assert calls == [None, "cur-2"]

    @respx.mock
    async def test_collect_cursor_pagination_is_capped(self, galxe_enabled) -> None:
        """永远有 endCursor 时翻页封顶（API 异常态不烧配额）。"""
        counter = {"n": 0}

        def _always_more(request: httpx.Request) -> Response:
            counter["n"] += 1
            return Response(
                200,
                json={
                    "data": {
                        "campaigns": {
                            "totalCount": 10_000,
                            "list": [
                                {
                                    "id": f"gc-{counter['n']}",
                                    "name": f"Campaign {counter['n']}",
                                    "status": "ACTIVE",
                                    "rewardType": "OAT",
                                    "space": {"id": "sp1", "name": "NovaLayer", "alias": "novalayer"},
                                }
                            ],
                            "pageInfo": {"hasNextPage": True, "endCursor": f"c-{counter['n']}"},
                        }
                    }
                },
            )

        respx.post("https://graphigo.prd.galaxy.eco/query").mock(side_effect=_always_more)

        collector = GalxeCollector()
        result = await collector.collect()

        assert counter["n"] == collector.MAX_CURSOR_PAGES, "cursor 翻页未封顶"
        assert len(result.items) == collector.MAX_CURSOR_PAGES
