"""采集器快赢修复回归（2026-11-14 审查 P3）。

- etherscan `_contract_name` 取地址前 10 位当名称 → 前缀相同的合约共享
  dedup_key 误合并（概率低但随时间累积）；改用完整地址。
- farcaster 查询串的 parent_url 未 URL 编码（含 `: / ~`）。
- galxe 对非对象响应（list/str）没有清晰报错 —— `"errors" in data` 对
  字符串做的是子串匹配，语义完全不对。
"""

from __future__ import annotations

import httpx
import pytest
import respx
from httpx import Response

from app.collectors.etherscan import EtherscanCollector
from app.collectors.galxe import GalxeCollector


def test_etherscan_contract_names_differ_for_prefix_sharing_addresses() -> None:
    """前 10 位相同的两个地址必须得到不同的名称（dedup_key 不能撞）。"""
    collector = EtherscanCollector()
    a = collector._contract_name("0xAAAAAAAAAA111111111111111111111111111111")
    b = collector._contract_name("0xAAAAAAAAAA222222222222222222222222222222")

    assert a != b, f"前缀共享的两个地址生成了同名 dedup 依据：{a!r}"
    assert a.startswith("Contract 0x"), "名称仍应保留 Contract 前缀的展示语义"


@respx.mock
async def test_farcaster_query_url_is_percent_encoded(monkeypatch: pytest.MonkeyPatch) -> None:
    """parent_url（含 : / ~）必须经过 percent-encoding，不能裸拼进 query。"""
    from app.collectors.farcaster import FarcasterCollector

    captured_urls: list[str] = []

    def _capture(request: httpx.Request) -> Response:
        captured_urls.append(str(request.url))
        return Response(200, json={"messages": []})

    respx.get(path="/v1/castsByParent").mock(side_effect=_capture)

    collector = FarcasterCollector()
    monkeypatch.setattr(collector, "channels", ["python"])
    # 走真实的 _fetch 路径（URL 编码发生在那里，手工拼 URL 测不到）
    result = await collector.collect()

    assert result.status in ("success", "partial"), result.error_message
    assert captured_urls, "没有发出请求 —— mock 配置失效"
    from urllib.parse import parse_qs, unquote, urlparse

    qs = parse_qs(urlparse(captured_urls[0]).query)
    # 无论是否编码，服务端看到的参数值都一样；契约是**线上传输必须编码**
    assert "%2F" in captured_urls[0] or "%3A" in captured_urls[0], (
        f"parent_url 未做 percent-encoding（裸拼特殊字符）：{captured_urls[0]}"
    )
    decoded = unquote(qs["url"][0]) if "url" in qs else ""
    assert decoded.startswith("https://farcaster.xyz/~/channel/"), f"参数值被编码破坏：{decoded}"


@respx.mock
async def test_galxe_non_object_payload_raises_clear_error() -> None:
    """GraphQL 返回非对象（list/str）时给清晰 ValueError，而不是 AttributeError。"""
    respx.post("https://graphigo.prd.galaxy.eco/query").mock(return_value=Response(200, json=[]))

    collector = GalxeCollector()
    result = await collector.collect()

    assert result.status == "error"
    assert result.error_message is not None
    assert "非对象" in result.error_message or "non-object" in result.error_message, (
        f"非对象响应的错误信息不清晰：{result.error_message!r}"
    )
