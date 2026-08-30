"""Tests for outbound HTTP domain allowlist (SECURITY §10.2).

覆盖两层白名单：
- 静态采集器 / 已知 API 域名（`_KNOWN_DOMAINS`）
- 动态 LLM provider 域名（从 `settings.llm_providers` 推导，放行自建代理）
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.utils.domain_allowlist import (
    _KNOWN_DOMAINS,
    DomainNotAllowedError,
    allowed_domains,
    assert_url_allowed,
    is_url_allowed,
)


class TestKnownDomains:
    def test_collector_domains_present(self) -> None:
        # 与 SECURITY §10.2 已对账的表一致（含 Galxe 的正确主机名与本批 4 个 P2 源）
        for host in (
            "api.llama.fi",
            "api.github.com",
            "api.coingecko.com",
            "api.cryptorank.io",
            "api.rootdata.com",
            "api.twitter.com",
            "api.etherscan.io",
            "api.layer3.xyz",
            "graphigo.prd.galaxy.eco",
            "discord.com",
            "www.reddit.com",
            "oauth.reddit.com",
            "medium.com",
            "arweave.net",
        ):
            assert host in _KNOWN_DOMAINS

    def test_is_url_allowed_known(self) -> None:
        assert is_url_allowed("https://api.llama.fi/protocols") is True

    def test_is_url_allowed_rejects_unknown(self) -> None:
        assert is_url_allowed("https://evil.example.com/steal") is False

    def test_is_url_allowed_rejects_non_http(self) -> None:
        # fail-closed：非 http/https / 解析不出 host / 空串 一律不允许
        assert is_url_allowed("ftp://api.llama.fi/x") is False
        assert is_url_allowed("just-a-string") is False
        assert is_url_allowed("") is False

    def test_assert_raises_on_unknown(self) -> None:
        with pytest.raises(DomainNotAllowedError):
            assert_url_allowed("https://evil.example.com/x")

    def test_assert_passes_on_known(self) -> None:
        # 不抛异常即通过
        assert_url_allowed("https://api.github.com/repos/x/y")


class TestDynamicLLMDomains:
    def test_llm_provider_domains_are_included(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置的自建 LLM 代理域名应动态放行，而不是被静态白名单误拦。"""
        mock_settings = MagicMock()
        mock_settings.llm_providers = [
            {
                "base_url": "https://custom-llm-proxy.example.com/v1",
                "api_key": "k",
                "name": "p1",
                "models": ["m"],
            },
        ]
        monkeypatch.setattr("app.utils.domain_allowlist.settings", mock_settings)

        domains = allowed_domains()
        assert "custom-llm-proxy.example.com" in domains
        assert is_url_allowed("https://custom-llm-proxy.example.com/v1/chat/completions") is True

    def test_unknown_domain_still_rejected_with_llm_providers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """即使配置了 LLM provider，表外域名仍然被拒绝。"""
        mock_settings = MagicMock()
        mock_settings.llm_providers = [
            {
                "base_url": "https://custom-llm-proxy.example.com/v1",
                "api_key": "k",
                "name": "p1",
                "models": ["m"],
            },
        ]
        monkeypatch.setattr("app.utils.domain_allowlist.settings", mock_settings)

        assert is_url_allowed("https://evil.example.com/x") is False


class TestFetchIntegration:
    """`fetch()` 入口已接入 `assert_url_allowed` —— 表外域名直接拒绝、不发请求。"""

    @pytest.mark.asyncio
    async def test_fetch_rejects_unknown_domain(self) -> None:
        from app.utils.fetcher import fetch

        with pytest.raises(DomainNotAllowedError):
            await fetch("https://evil.example.com/x")


class TestCollectorBaseUrlsConsistent:
    """settings 里采集器 base_url 的域名必须都在白名单内（防改配置后漂移）。"""

    def test_settings_collector_base_urls_are_allowed(self) -> None:
        from app.config import settings

        for attr in (
            "defillama_base_url",
            "github_api_base_url",
            "coingecko_api_base_url",
            "cryptorank_base_url",
            "rootdata_base_url",
        ):
            url = getattr(settings, attr)
            assert is_url_allowed(url), f"{attr}={url} 不在出站域名白名单里"
