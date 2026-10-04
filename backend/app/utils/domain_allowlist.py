"""Outbound HTTP domain allowlist (SECURITY §10.2「出站域名白名单」).

背景：此前仓库里**没有任何代码在拒绝表外域名** —— 采集器、LLM 客户端、
通用 fetcher 各自发请求，改一行 URL 就能访问任意域名（实测 2026-08-23，
全仓 0 处域名白名单相关符号）。这是 SSRF 的技术缺口。

本模块提供集中出站域名白名单：

- 采集器 / 已知 API 域名：**静态**（`_KNOWN_DOMAINS`，与 SECURITY §10.2
  已对账的那张表一致 —— Galxe 主机名、RootData 漏登记都已修正，见
  `test_security_doc_parity.py::TestDomainWhitelistTable`）。
- LLM provider 域名：**动态**（从 `settings.llm_providers` 推导）。LLM 的
  base_url 是运行时决定的（`LLM_BASEURL_{i}` / 自建代理 / 本地 ollama），
  无法静态穷举 —— 但任何**已配置**的 provider 域名都应该放行。

**运行时强制范围（重要，别夸大）**：在发请求前调 `assert_url_allowed()` 的出口有
通用 fetcher（`utils/fetcher.py`）、LLM 客户端（`llm/client.py`）与全部采集器
（`collectors/base.py::safe_collector_client` 的 request hook，含重定向每一跳）。
采集器的 host 另由 `test_domain_allowlist.py::TestKnownDomains` 与
`test_security_doc_parity.py`（§10.2 表对账）钉住，新增 host 不登记会让 CI 变红。

不走本白名单的：`services/vitals.py`（按解析 IP 拒绝非公网目标）；
faucet_registry / public_rpc_verifier / defillama_raises / ops_tasks（目标为写死常量）。
见 SECURITY §10.2。
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
        "discord.com",  # Discord bot API
        "www.reddit.com",  # Reddit OAuth token 端点
        "oauth.reddit.com",  # Reddit OAuth API
        "medium.com",  # Medium RSS tag feed
        "arweave.net",  # Mirror（经 Arweave GraphQL 公开读）
        "t.me",  # Telegram 公开频道 Web 预览（DATA_SOURCE_STRATEGY §2）
        "hub.pinata.cloud",  # Farcaster 公开 Hubble HTTP 节点（DATA_SOURCE_STRATEGY §2）
        "api.telegram.org",  # Telegram Bot API（决策推送 sendMessage，ACTION_LOOP_DESIGN §2）
        "raw.githubusercontent.com",  # GitHub Curated lists (github_curated)
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
