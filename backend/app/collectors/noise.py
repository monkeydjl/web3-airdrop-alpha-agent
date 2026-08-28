"""Shared noise denylist for collectors and analysis queue.

Used by DefiLlama filtering and analysis-entry skip so historical
raw_projects cannot re-score CEX / blue-chip brands.
"""

from __future__ import annotations

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
    if any(slug_l.startswith(p) or name_l.startswith(p) for p in SLUG_DENY_PREFIXES):
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
