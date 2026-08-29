"""Outbound HTTP domain allowlist (SECURITY §10.2「统一的 HTTP 出口」).

背景：此前仓库里**没有任何代码在拒绝表外域名** —— 采集器、LLM 客户端、
通用 fetcher 各自发请求，改一行 URL 就能访问任意域名（实测 2026-08-23，
全仓 0 处域名白名单相关符号）。这是 SSRF 的技术缺口。

本模块提供一处集中的域名白名单：

- 采集器 / 已知 API 域名：**静态**（`_COLLECTOR_DOMAINS`，与
  SECURITY §10.2 已对账的那张表一致 —— Galxe 主机名、RootData 漏登记
  都已修正，见 `test_security_doc_parity.py::TestDomainWhitelistTable`）。
- LLM provider 域名：**动态**（从 `settings.llm_providers` 推导）。LLM 的
  base_url 是运行时决定的（`LLM_BASEURL_{i}` / 自建代理 / 本地 ollama），
  无法静态穷举 —— 但任何**已配置**的 provider 域名都应该放行。

消费方在发出请求前调 `assert_url_allowed()`；命中表外域名抛
`DomainNotAllowedError`。**fail-closed**：解析不出 host 的 URL 一律拒绝，
而不是静默放行。
"""

from __future__ import annotations

from urllib.parse import urlparse

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)

# 采集器 / 已知 API 的静态白名单（SECURITY §10.2 表，2026-08-23 已对账）。
_KNOWN_DOMAINS: frozenset[str] = frozenset(
    {
        "api.llama.fi",  # DefiLlama
        "api.github.com",  # GitHub
        "api.coingecko.com",  # CoinGecko
        "api.cryptorank.io",  # CryptoRank
        "api.rootdata.com",  # RootData
        "api.twitter.com",  # Twitter/X
        "api.etherscan.io",  # Etherscan
        "api.layer3.xyz",  # Layer3
        "graphigo.prd.galaxy.eco",  # Galxe（GraphQL 主机名，见 SECURITY §10.2）
        "api.openai.com",  # LLM 单接口默认 endpoint
    }
)


class DomainNotAllowedError(ValueError):
    """目标域名不在出站白名单里（SECURITY §10.2）。"""


def _host_of(url_or_base: str) -> str | None:
    """从 URL 字符串解析 host（小写），解析失败返回 None。"""
    try:
        parsed = urlparse(url_or_base.strip())
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    # 必须显式 http/https；像 `sk-xxx` 这种会被 urlparse 当 scheme 的东西，
    # hostname 会是 None，正好被下面 fail-closed 拒绝。
    if parsed.scheme not in ("http", "https"):
        return None
    return host or None


def allowed_domains() -> frozenset[str]:
    """当前生效的出站白名单 = 静态已知域名 ∪ 运行时 LLM provider 域名。"""
    domains: set[str] = set(_KNOWN_DOMAINS)
    for provider in settings.llm_providers:
        host = _host_of(str(provider.get("base_url", "")))
        if host:
            domains.add(host)
    return frozenset(domains)


def is_url_allowed(url: str) -> bool:
    """目标 URL 的 host 是否在白名单内。"""
    host = _host_of(url)
    return host is not None and host in allowed_domains()


def assert_url_allowed(url: str) -> None:
    """发出请求前校验 URL 的域名在白名单内，否则抛 `DomainNotAllowedError`。

    fail-closed：解析不出 host（非 http/https、缺 host）也算不允许。
    """
    host = _host_of(url)
    if host is None or host not in allowed_domains():
        logger.error("security.domain_not_allowed", url=url, host=host)
        raise DomainNotAllowedError(f"target domain not in outbound allowlist: {host or '<unparseable>'} (url={url})")
