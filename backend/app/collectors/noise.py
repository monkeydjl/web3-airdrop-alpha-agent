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
    has_points_program: bool = False,
    has_task_portal: bool = False,
    explicit_airdrop_mention: bool = False,
    source_id: str = "",
    token_launch_confirmed: bool | None = None,
    explicit_points_program: bool | None = None,
) -> bool:
    """Return True if the project already has a listed token and no follow-on airdrop path.

    These projects have no airdrop alpha value — the token is already trading and
    there is no points program, quest portal, or explicit airdrop mention to suggest
    a further distribution.

    口径与 ADR-015 的 `has_post_launch_airdrop_path()` 完全一致（2026-10-06）：
    **testnet 不算**已发币项目的后续路径。此前这里把 has_testnet 也算进去，
    于是「已发币 + 只有测试网」的项目能过入库门、写进 projects，再被评分层
    的 already_launched 否决打成 IGNORE —— 已发币项目照样出现在库里。
    两道门用同一口径后，这类项目停在 raw_projects 的隔离区。

    只拦**确认已发币**的行：`token_launch_confirmed=False`（无发币证据、状态未知）
    一律放行 —— 2026-10-08 清理时按旧口径误删了约 30 个 RootData 项目，它们的
    `token_symbol` 为空，并无发币证据。

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
    # 「没确认未发币」≠「确认已发币」（2026-10-08）：来源给不出发币证据时
    # （RootData 免费档缺 token 字段、文本类来源），照常入库评分，不隔离。
    # None = 旧调用方未提供，按 not no_token_yet 兼容。
    if token_launch_confirmed is False:
        return False

    # Token is listed. Keep only with a post-launch airdrop path.
    # 积分只认严格证据（2026-10-08，与 has_post_launch_airdrop_path 同口径）；
    # None = 旧调用方未提供，回退宽松的 has_points_program。
    points = has_points_program if explicit_points_program is None else explicit_points_program
    has_post_launch_path = points or has_task_portal or explicit_airdrop_mention

    return not has_post_launch_path


# ── RootData 非项目实体（2026-10-08）────────────────────────────────────────
# RootData `/open/ser_inv` 是「项目 / 机构 / 人物」混合搜索，条目带 `type`：
# 1=项目、2=机构（VC）、3=人物、5=社媒账号 / 列表。只有 1 是项目。生产库泄漏
# 样例：Deirdre Connolly、airdropkorea、AIRDROP_ATM（type=3），
# "✨📋 Complete Web3 Testnets for Airdrops 🚀"（type=5）—— 全部以项目身份入库。
# 按 type 结构化判定，而不是按名字拉黑名单：名字黑名单永远追不上新的人名。
ROOTDATA_PROJECT_TYPE = 1


def is_rootdata_non_project(item: dict[str, Any]) -> bool:
    """RootData 搜索条目是人物 / 机构 / 社媒等非项目实体。

    缺 `type` 或值无法解析时返回 False（放行）：老数据与详情接口合并后的条目
    未必带这个字段，缺证据不等于不是项目。
    """
    raw = item.get("type")
    if raw is None or isinstance(raw, bool):
        return False
    try:
        return int(raw) != ROOTDATA_PROJECT_TYPE
    except (TypeError, ValueError):
        return False


# ── 工具类仓库（2026-10-06）────────────────────────────────────────────────
# GitHub 搜 "airdrop testnet" 返回的大多是撸毛脚本：Pharos-Auto-Bot、
# units-network-bot、solana-devnet-faucet……它们说明某个项目**正被很多人撸**，
# 本身不是项目。生产库实测：github 源 15 条全是这类仓库，13 条被判 FARM。
# 只对 github 源使用 —— 描述里的 "bot for" 在别的源可能是真项目（交易 bot 协议）。
_TOOLING_NAME_TOKENS = frozenset(
    {
        "bot",
        "bots",
        "autobot",
        "autobots",
        "automation",
        "automator",
        "script",
        "scripts",
        "farmer",
        "farming",
        "claimer",
        "sniper",
        "faucet",
        "faucets",
        "guide",
        "guides",
        "tutorial",
        "tutorials",
    }
)

_TOOLING_TOPICS = frozenset(
    {
        "bot",
        "bots",
        "automation",
        "airdrop-farming",
        "web3-farming",
    }
)

_TOOLING_DESC_RE = re.compile(
    r"""(?<![a-z0-9])(?:
        auto(?:mated|mation)?[\s-]?bot
        | bot\s+for
        | multi[\s-]?wallets?
        | multi[\s-]?accounts?
        | multiple\s+(?:wallets|accounts|private\s+keys)
        | airdrop\s+farming
        | script\s+collection
        | auto[\s-]?(?:swaps?|claims?|mint(?:ing)?|bridg(?:e|ing)|faucets?|transactions?|tasks?|referrals?)
        | stars?\s+to\s+unlock
    )(?![a-z0-9])""",
    re.IGNORECASE | re.VERBOSE,
)


def is_tooling_repo(*, name: str, description: str = "", topics: Any = None) -> bool:
    """GitHub 仓库是撸毛脚本 / 机器人 / 水龙头 / 教程这类工具，而非项目本身。

    三路任一命中即判定：名字分词（Pharos-Auto-Bot → bot）、topics
    （bot / airdrop-farming / *-bot）、描述措辞（automated bot、multiple
    private keys、auto swap）。
    """
    tokens = re.split(r"[\s\-_./]+", (name or "").strip().lower())
    if any(tok in _TOOLING_NAME_TOKENS for tok in tokens):
        return True

    topic_list = topics if isinstance(topics, (list, tuple)) else ()
    for topic in topic_list:
        t = str(topic).strip().lower()
        if t in _TOOLING_TOPICS or t.endswith("-bot") or t.endswith("-bots"):
            return True

    return bool(_TOOLING_DESC_RE.search(description or ""))


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
        # 2026-10-06 补充：github_curated 内置清单里长期以「未发币测试网」身份
        # 入库的品牌，逐个核实已 TGE。Story / Movement 首词是通用词，不收，
        # 避免误伤同名新项目（它们已从内置清单移除，不依赖本名单拦截）。
        "monad",  # MON TGE 2025-11-24
        "megaeth",  # MEGA TGE 2026-04-30
        "babylon",  # BABY TGE 2025-04-10
        "initia",  # INIT TGE 2025-04-24
        "nesa",  # NES 上线 2026-06-24
    }
)

# 通用词不配当品牌：'XX Mainnet' 的首词 mainnet 不能代表品牌，否则
# "Mainnet Finance" 会被 "Plume Mainnet" 误伤。
_BRAND_STOPLIST = frozenset(
    {
        "mainnet",
        "finance",
        "swap",
        "vault",
        "vaults",
        "network",
        "chain",
        "protocol",
        "defi",
        "labs",
        "staking",
        "points",
        "testnet",
        "liquid",
        "pool",
        "pools",
        "token",
        "bridge",
        "portal",
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
