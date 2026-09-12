"""Shared noise denylist for collectors and analysis queue.

Used by DefiLlama filtering and analysis-entry skip so historical
raw_projects cannot re-score CEX / blue-chip brands.
"""

from __future__ import annotations

import re
from typing import Any

# Categories that are not early airdrop alpha
CATEGORY_DENY = frozenset(
    {
        "cex",
        "cexs",
        "chain",
    }
)

# Mature brands / CEX / stables that often appear without gecko_id on child rows
NAME_DENY_SUBSTRINGS = (
    "uniswap",
    "aave",
    "curve",
    "balancer",
    "sushiswap",
    "compound",
    "makerdao",
    "yearn",
    "lido",
    "coinbase",
    "crypto.com",  # CDC 的质押/LSDFi 产品线，成熟品牌无空投 alpha
    "binance",
    "okx",
    "bybit",
    "bingx",
    "bitget",
    "kraken",
    "kucoin",
    "gate.io",
    "gateio",
    "huobi",
    "mexc",
    "zoomex",
    "blackrock",
    "fidelity",
    "vaneck",
    "wisdomtree",
    "weth",
    "steth",
    "usdc",
    "usdt",
    "dai ",
    "wrapped",
    "pancakeswap",
    "1inch",
    "opensea",
    "etherfi",  # liquid restaking brand variants often already liquid
)

SLUG_DENY_PREFIXES = (
    "uniswap",
    "aave",
    "curve-",
    "balancer",
    "sushiswap",
    "compound-",
    "lido",
    "coinbase",
    "binance",
    "yearn",
    "zoomex",
    "bingx",
    "bitget",
    "okx-",
    "bybit",
    "pancakeswap",
)

PARENT_DENY_SUBSTRINGS = (
    "uniswap",
    "aave",
    "curve",
    "balancer",
    "lido",
    "yearn",
    "compound",
    "sushiswap",
    "maker",
)

# RWA 凭据类资产：代币化证券 / 国债 / 基金份额 / 股票（2026-09 新增）。
# 它们是资产claim的链上凭证，不是"可能空投的项目"——出现在 pre-TGE 候选池
# 里纯属噪声（生产库泄漏样例：Securitize Tokenized AAA CLO Fund、
# MatrixDock STBT、Bitwise USCC、Spiko、Midas RWA、xStocks、Figure Markets）。
# 注意不能按 category=RWA 整类拒绝：GAIB / Hastra / OnRe / Kasu 是真实的
# pre-TGE 协议，会被误伤——只按品牌/产品名精确匹配。
RWA_CREDENTIAL_DENY_SUBSTRINGS = (
    "securitize",  # Securitize 系代币化基金（Apollo AAA CLO 等）
    "matrixdock",  # STBT 代币化短期国债
    "stbt",
    "uscc",  # Bitwise 代币化国债
    "spiko",  # 代币化欧元国债 / 货币市场基金
    "midas rwa",  # Midas 代币化国债产品线（勿匹配裸 "midas"，会误伤同名新项目）
    "xstocks",  # Backed 代币化股票
    "figure markets",  # Figure 证券交易市场
    "subfrost",  # Stacks BTC 质押凭据
)

# 封装/质押 BTC 凭据变体：token 恰为 "btc"（"Nexus BTC"、"BitFi BTC"），
# 或以 "btc" 结尾的紧凑变体（wbtc / tzbtc / sbtc / ybtc / fbtc / gtbtc /
# solvbtc / obeliskbtc…，前缀 1–10 个字母数字）。BTCFi 之类**前缀**词
# 不受影响（"btcfi" 不以 btc 结尾）。
_BTC_CREDENTIAL_TOKEN_RE = re.compile(r"^[a-z0-9]{1,10}btc$")


def _is_btc_credential(name: str, slug: str) -> bool:
    """名字/slug 的任一 token 是 BTC 凭据（独立 "btc" 词或 xxxBTC 变体）。"""
    tokens = re.split(r"[\s\-_/]+", f"{(name or '').lower()} {(slug or '').lower()}")
    return any(tok == "btc" or _BTC_CREDENTIAL_TOKEN_RE.match(tok) for tok in tokens)


def is_noise_project(
    *,
    name: str = "",
    slug: str = "",
    category: str = "",
    parent: str = "",
    sector: str = "",
) -> bool:
    """Return True if the project should not enter discovery/analysis as alpha."""
    cat = (category or sector or "").strip().lower()
    if cat in CATEGORY_DENY or cat == "cex" or "cex" in cat.split():
        return True

    name_l = (name or "").lower()
    slug_l = (slug or "").lower()
    parent_l = (parent or "").lower()
    blob = f"{name_l} {slug_l} {parent_l}"

    if any(s in blob for s in NAME_DENY_SUBSTRINGS):
        return True
    if any(s in blob for s in RWA_CREDENTIAL_DENY_SUBSTRINGS):
        return True
    if any(slug_l.startswith(p) or name_l.startswith(p) for p in SLUG_DENY_PREFIXES):
        return True
    if _is_btc_credential(name or "", slug or ""):
        return True
    return bool(parent_l and any(s in parent_l for s in PARENT_DENY_SUBSTRINGS))


def is_noise_protocol(protocol: dict[str, Any]) -> bool:
    """DefiLlama protocol dict → noise?"""
    return is_noise_project(
        name=str(protocol.get("name") or ""),
        slug=str(protocol.get("slug") or ""),
        category=str(protocol.get("category") or ""),
        parent=str(protocol.get("parentProtocol") or ""),
    )


def is_noise_raw_project(name: str, sector: str | None = None, raw_data: dict[str, Any] | None = None) -> bool:
    """Analysis queue helper from name + optional raw_data."""
    raw = raw_data or {}
    return is_noise_project(
        name=name or str(raw.get("name") or ""),
        slug=str(raw.get("slug") or ""),
        category=str(raw.get("category") or sector or raw.get("sector") or ""),
        parent=str(raw.get("parentProtocol") or raw.get("parent") or ""),
        sector=str(sector or raw.get("sector") or ""),
    )


def is_listed_token_no_airdrop_signals(
    *,
    no_token_yet: bool,
    has_testnet: bool = False,
    has_points_program: bool = False,
    has_task_portal: bool = False,
    explicit_airdrop_mention: bool = False,
    source_id: str = "",
) -> bool:
    """Return True if the project already has a listed token and zero airdrop signals.

    These projects have no airdrop alpha value — the token is already trading and
    there are no testnet, points, quest, or airdrop mentions to suggest an upcoming
    distribution.

    Signal supplement sources (coingecko, cryptorank, etherscan) are exempt:
    their job is to provide token-listed corroboration for projects discovered by
    other sources. Filtering them would break cross-source merge.
    """
    # Signal supplement sources are never filtered here
    if source_id in ("coingecko", "cryptorank", "etherscan", "alchemy_webhook"):
        return False

    # If token not yet listed, it's potential alpha — keep it
    if no_token_yet:
        return False

    # Token is listed. Check for any airdrop-related signals
    has_any_airdrop_signal = has_testnet or has_points_program or has_task_portal or explicit_airdrop_mention

    return not has_any_airdrop_signal


# 已发币品牌的静态兜底名单 —— 只收有公开 TGE 证据的品牌，宁缺勿滥。
# DefiLlama 的 parentProtocol 链接常为 null（Plume Vaults → null），名字前缀
# 规则也接不住互不为前缀的对（"Plume Vaults" vs "Plume Mainnet"），按品牌
# 首词兜底是最后一条线。新品牌有 TGE 证据后往这里加一行。
KNOWN_LISTED_BRANDS = frozenset(
    {
        "plume",  # PLUME TGE 2025
        "zksync",  # ZK TGE 2024-06
        "berachain",  # BERA TGE 2025-02
        "scroll",  # SCR TGE 2024-10
        "celestia",  # TIA TGE 2023-10
        "pyth",  # PYTH TGE 2023-11
        "layerzero",  # ZRO TGE 2024-06
        "eigenlayer",  # EIGEN TGE 2024-10
        "hyperliquid",  # HYPE TGE 2024-11
    }
)

# 通用词不配当品牌：'XX Mainnet' 的首词 mainnet 不能代表品牌，否则
# "Mainnet Finance" 会被 "Plume Mainnet" 误伤。
_BRAND_STOPLIST = frozenset(
    {
        "mainnet", "finance", "swap", "vault", "vaults", "network", "chain",
        "protocol", "defi", "labs", "staking", "points", "testnet", "liquid",
        "pool", "pools", "token", "bridge", "portal",
    }
)


def _brand_token(name: str) -> str:
    """取名字的**首词**作为品牌词；通用词、过短词（<4）、纯数字返回空串。

    只取首词是有意的：品牌在名字头部（"Plume Vaults" 的品牌是 plume），
    而 "Mystic Finance myPLUME" 里的 myplume 只是衍生品名，中段匹配会误杀。
    """
    tokens = re.split(r"[\s\-_/]+", (name or "").strip().lower())
    tok = tokens[0] if tokens else ""
    if not tok or tok in _BRAND_STOPLIST or len(tok) < 4 or tok.isdigit():
        return ""
    return tok


def is_listed_brand_subproduct(
    *,
    name: str,
    slug: str = "",
    brands: frozenset[str] | None = None,
) -> bool:
    """名字/slug 的品牌首词命中已发币品牌 → 判为已发币品牌的子产品。

    与 is_listed_token_no_airdrop_signals 的分工：那边判定「已发币且无信号
    → 丢」，这边只回答「它是不是已发币品牌的子产品」，供采集器 facet 过滤
    与存量追溯脚本共用。调用方仍需检查子产品自有空投信号。
    """
    registry = KNOWN_LISTED_BRANDS if brands is None else frozenset(brands)
    brand = _brand_token(name) or _brand_token(slug)
    return bool(brand) and brand in registry
