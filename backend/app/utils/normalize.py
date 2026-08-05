"""Normalization and deduplication logic.

Handles project name/sector normalization and cross-source deduplication.

Reference:
- ENGINEERING_ROADMAP.md §6.2.1 归一化与去重
- TASK_BREAKDOWN.md W2-02
"""

import json
import unicodedata
import uuid
from datetime import UTC
from typing import NamedTuple

import structlog

logger = structlog.get_logger(__name__)


# Sector alias mapping (same sector, different names)
SECTOR_ALIAS = {
    # Layer 2
    "layer2": "L2",
    "l2": "L2",
    "layer-2": "L2",
    "layer 2": "L2",
    # Restaking
    "restake": "Restaking",
    "restaking": "Restaking",
    "re-staking": "Restaking",
    # DeFi variations
    "defi": "DeFi",
    "de-fi": "DeFi",
    "decentralized finance": "DeFi",
    # Gaming
    "gaming": "Gaming",
    "game": "Gaming",
    "gamefi": "GameFi",
    # Infrastructure
    "infra": "Infrastructure",
    "infrastructure": "Infrastructure",
    # NFT
    "nft": "NFT",
    "nfts": "NFT",
    "non-fungible token": "NFT",
    # DAO
    "dao": "DAO",
    "daos": "DAO",
    # DEX
    "dex": "DEX",
    "decentralized exchange": "DEX",
    # Lending
    "lending": "Lending",
    "loan": "Lending",
    "borrow": "Lending",
    # Bridge
    "bridge": "Bridge",
    "cross-chain": "Bridge",
    # Privacy
    "privacy": "Privacy",
    "private": "Privacy",
    "zero-knowledge": "ZK",
    "zk": "ZK",
    # AI
    "ai": "AI",
    "artificial intelligence": "AI",
    "machine learning": "AI",
}


# Common suffixes to remove from project names
PROJECT_SUFFIXES = [
    "protocol",
    "finance",
    "network",
    "chain",
    "dao",
    "labs",
    "foundation",
    "app",
    "dapp",
    "platform",
]


def normalize_name(name: str) -> str:
    """Normalize project name for deduplication.

    Steps:
    1. Lowercase
    2. Remove spaces and hyphens
    3. Remove common suffixes
    4. Unicode NFKC normalization

    Args:
        name: Raw project name

    Returns:
        Normalized name key

    Examples:
        >>> normalize_name("LayerX")
        'layerx'
        >>> normalize_name("Layer-X Finance")
        'layerx'
        >>> normalize_name("Layer X Protocol")
        'layerx'
    """
    if not name:
        return ""

    # Step 1: Lowercase
    normalized = name.lower()

    # Step 2: Remove spaces and hyphens
    normalized = normalized.replace(" ", "").replace("-", "").replace("_", "")

    # Step 3: Remove common suffixes
    for suffix in PROJECT_SUFFIXES:
        if normalized.endswith(suffix):
            normalized = normalized[: -len(suffix)]

    # Step 4: Unicode NFKC normalization
    normalized = unicodedata.normalize("NFKC", normalized)

    return normalized


def normalize_sector(sector: str) -> str:
    """Normalize sector name using alias mapping.

    Maps synonyms to canonical sector names.

    Args:
        sector: Raw sector name

    Returns:
        Canonical sector name

    Examples:
        >>> normalize_sector("layer2")
        'L2'
        >>> normalize_sector("restaking")
        'Restaking'
        >>> normalize_sector("Unknown Sector")
        'Unknown Sector'
    """
    if not sector:
        return "Unknown"

    # Lowercase for lookup
    lookup_key = sector.lower().strip()

    # Return canonical name if found, otherwise return original (title case)
    return SECTOR_ALIAS.get(lookup_key, sector.strip().title())


class DedupKey(NamedTuple):
    """Deduplication key for projects.

    Combines normalized name and sector.
    """

    name_key: str
    sector_key: str

    def to_string(self) -> str:
        """Convert to string format: name::sector"""
        return f"{self.name_key}::{self.sector_key}"

    @classmethod
    def from_string(cls, key_str: str) -> "DedupKey":
        """Parse from string format"""
        parts = key_str.split("::")
        if len(parts) != 2:
            raise ValueError(f"Invalid dedup_key format: {key_str}")
        return cls(name_key=parts[0], sector_key=parts[1])


def create_dedup_key(name: str, sector: str | None = None) -> DedupKey:
    """Create deduplication key from project name and sector.

    Args:
        name: Project name
        sector: Project sector (optional)

    Returns:
        DedupKey namedtuple

    Examples:
        >>> key = create_dedup_key("LayerX", "L2")
        >>> key.to_string()
        'layerx::L2'
    """
    name_key = normalize_name(name)
    sector_key = normalize_sector(sector or "Unknown")

    return DedupKey(name_key=name_key, sector_key=sector_key)


def generate_deterministic_id(dedup_key: DedupKey) -> str:
    """Generate deterministic UUID v5 from dedup key.

    Ensures same project gets same ID across runs.

    Args:
        dedup_key: Deduplication key

    Returns:
        UUID string

    Examples:
        >>> key = DedupKey("layerx", "l2")
        >>> id1 = generate_deterministic_id(key)
        >>> id2 = generate_deterministic_id(key)
        >>> id1 == id2
        True
    """
    # Use DNS namespace as base
    namespace = uuid.NAMESPACE_DNS
    key_str = dedup_key.to_string()

    # Generate UUID v5 (deterministic)
    project_uuid = uuid.uuid5(namespace, key_str)

    return str(project_uuid)


# Source priority for conflict resolution (lower = higher priority)
SOURCE_PRIORITY = {
    "manual": 0,  # User manual input (highest)
    "api": 1,  # API input
    "seed": 2,  # Seed data
    "defillama": 3,
    "coingecko": 4,
    "github": 5,
    "rootdata": 5,  # funding quality — merge ahead of twitter noise
    "cryptorank": 6,
    # 任务门户类源：空投证据(任务入口/积分)的第一手来源，必须优先于 twitter 噪声。
    # 此前缺失导致其回落到 unknown=99，永远当不上 primary，携带的强空投信号被丢弃。
    "galxe": 6,
    "layer3": 6,
    "etherscan": 6,
    "twitter_kol": 7,
    "twitter_keyword": 8,
    "twitter": 9,  # Generic twitter fallback
    "unknown": 99,
}

# ── 跨源字段合并策略 ─────────────────────────────────────────────────────────
#
# 前提：抵达 `merge_raw_records` 的是**已归一化的整行**，缺失的布尔一律填成
# `False`、缺失的计数一律填成 `0`。所以对爬取类来源，`False`/`0` 的含义是
# **"这个源没看到"**，而不是"这个源核实了它不存在"。
#
# 由此分两类处理：
#
# 1) 存在性/规模类字段（has_*、explicit_airdrop_mention、github_stars、tvl_usd …）
#    在全部来源上做 OR / max。这**不违反** DATA_QUALITY.md §128：§128 裁决的是
#    "同字段多源冲突"，而"我没看到" 与 "我看到了" 之间不构成冲突——看不见不等于
#    不存在。原实现按记录整体择一，落选来源的全部字段被一并丢弃，生产中最常见的
#    「信号丰富的任务门户源 + 信号稀疏的行情源」组合因此直接损失 23 个信号字段。
#
# 2) `manual` / `api` 是唯二能**主张否定**的来源：它们是人工/一方系统的刻意输入，
#    不是抓取产物，`False`/`0` 在这里是真实断言。这两类来源一旦对某字段给出显式
#    取值，就直接采信，不参与 OR/max——否则一条 twitter 噪声就能把人工确认的
#    "已发币"翻回 no_token_yet=True，把 airdrop_signal 从 20 顶到 100。
#
# 标量字段（url/sector/stage/…）走的是另一条路：取值本身就是断言，冲突是真冲突，
# 因此严格按 §128 取 reliability 最高且值已知的来源。
#
# 有资格主张否定的来源（其显式取值优先于 OR/max 合成）
_AUTHORITATIVE_SOURCES = ("manual", "api")

# 布尔证据：任一源观测到即成立（证据是"看见过"，看不见不等于不存在）
_MERGE_BOOL_OR = (
    "has_testnet",
    "has_points_program",
    "no_token_yet",
    "recent_funding",
    "has_docs",
    "has_whitepaper",
    "has_roadmap",
    "has_github",
    "has_twitter",
    "has_discord",
    "explicit_airdrop_mention",
    "has_task_portal",
    "has_contract",
)
# 数值证据：取最大（各源只会看到自己能看到的那部分）
_MERGE_NUMERIC_MAX = (
    "github_stars",
    "tvl_usd",
    "funding_total_usd",
    "funding_rounds",
    "funding_quality",
)
# 越小越强的数值：取最小（距上次推送天数，0 = 今天推送）
_MERGE_NUMERIC_MIN = ("github_recent_push_days",)
# 列表：按源优先级顺序并集
_MERGE_LIST_UNION = ("funding_investors", "funding_lead_investors")
# 标量：取"优先级最高且值已知"的源，跳过 None/""/unknown/none
_MERGE_SCALAR_BEST_KNOWN = (
    "url",
    "sector",
    "stage",
    "description",
    "funding_tier",
    "funding_last_date",
    "roadmap_delivery",
    "sybil_friction",
)
_UNKNOWN_SCALARS = {None, "", "unknown", "none", "None"}


def _is_unknown_scalar(value) -> bool:
    """值是否为"未知占位"。

    不能直接写 `value in _UNKNOWN_SCALARS`：这些字段来自外部 JSON，上游偶尔会给出
    list/dict（例如 description 被解析成数组），对不可哈希对象做集合成员测试会抛
    TypeError。而 `_dedup_records` 在 `collect_from_repository` 里位于逐行 try 之外，
    一条畸形记录会中断整批采集。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"", "unknown", "none"}
    if isinstance(value, (list, tuple, dict, set)):
        return not value
    return False


def _discovered_at_sort_key(value) -> tuple[int, float, str]:
    """discovered_at 的可比排序键（容忍字符串 / naive / aware 混用）。

    统一折算成 UTC 时间戳；无法解析时退到字符串比较，并排在可解析值之后，
    保证"取最早"仍优先选真正解析得出的时间。
    """
    from datetime import datetime as _dt

    parsed = value
    if isinstance(parsed, str):
        try:
            parsed = _dt.fromisoformat(parsed.replace("Z", "+00:00"))
        except ValueError:
            return (1, 0.0, parsed)
    if isinstance(parsed, _dt):
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return (0, parsed.timestamp(), "")
    return (1, 0.0, str(value))


def _record_priority(record: dict, source_key: str) -> int:
    return get_source_priority(str(record.get(source_key) or "unknown"))


def _merge_sort_key(record: dict, source_key: str) -> tuple[int, str, str]:
    """合并排序键：优先级 → 来源名 → 内容规范序（全序，保证顺序无关）。"""
    return (
        _record_priority(record, source_key),
        str(record.get(source_key) or "unknown"),
        json.dumps(record, sort_keys=True, default=str, ensure_ascii=False),
    )


def _known_field_records(records: list[dict], field: str, source_key: str) -> list[dict]:
    """返回对 `field` 有已知取值、且来源优先级并列最高的记录（§128 冲突裁决）。"""
    candidates = [r for r in records if field in r and not _is_unknown_scalar(r.get(field))]
    if not candidates:
        return []
    best = min(_record_priority(r, source_key) for r in candidates)
    return [r for r in candidates if _record_priority(r, source_key) == best]


def _authoritative_value(records: list[dict], field: str, source_key: str):
    """`manual`/`api` 对 `field` 的显式取值（无则返回 sentinel `_NO_VALUE`）。

    只有这两类来源是刻意输入而非抓取产物，它们的 `False`/`0` 是真实断言，
    必须优先于 OR/max 合成——否则一条爬取噪声就能推翻人工确认的结论。
    """
    for record in records:
        source = str(record.get(source_key) or "").lower()
        if source in _AUTHORITATIVE_SOURCES and field in record and record[field] is not None:
            return record[field]
    return _NO_VALUE


class _NoValue:
    __slots__ = ()


_NO_VALUE = _NoValue()


def get_source_priority(source: str) -> int:
    """Get priority for a data source.

    Args:
        source: Source name

    Returns:
        Priority (lower is better)
    """
    return SOURCE_PRIORITY.get(source.lower(), 99)


def merge_sources(sources: list[str]) -> str:
    """Merge multiple sources into comma-separated string.

    Args:
        sources: List of source names

    Returns:
        Comma-separated unique sources

    Examples:
        >>> merge_sources(["seed", "defillama", "seed"])
        'seed,defillama'
    """
    # 去重并按（优先级, 名称）排序。只按优先级排序时，同优先级的源之间保持的是
    # `set` 的迭代顺序，而那取决于 PYTHONHASHSEED——同样的输入在不同进程会写出
    # 不同的 `projects.source` 字符串，collector 又用 `source.split(",")[0]` 取
    # discovery_source，等于让该字段随机漂移。补上名称作为确定性 tiebreaker。
    unique_sources = sorted(set(sources), key=lambda s: (get_source_priority(s), s))
    return ",".join(unique_sources)


def merge_raw_records(
    records: list[dict],
    source_key: str = "source",
) -> dict:
    """Merge multiple raw project records into one canonical record.

    Resolution rules:
    1. Primary record: highest source priority (manual > api > seed > defillama > ...)
    2. Boolean signals: OR across all records (has_testnet, has_points_program, etc.)
    3. discovery_score: max across all records
    4. discovered_at: earliest non-null timestamp
    5. sources: merged and sorted by priority

    Args:
        records: List of raw project dicts (must contain at least 'name')
        source_key: Key for source field in record

    Returns:
        Merged canonical record dict

    Raises:
        ValueError: If records is empty
    """
    if not records:
        raise ValueError("records must not be empty")

    # 按（来源优先级, 来源名, 内容规范序）排序。只按优先级排序时结果依赖输入序：
    # github/rootdata 同为 5，cryptorank/galxe/layer3/etherscan 同为 6，而上游
    # `ORDER BY discovery_score DESC, discovered_at DESC` 没有唯一 tiebreaker；
    # 同一来源还可能出现多条记录。补上来源名与内容规范序后，同一组记录无论以什么
    # 顺序传进来都产出同一个合并结果。
    sorted_records = sorted(records, key=lambda r: _merge_sort_key(r, source_key))
    primary = sorted_records[0]

    merged = dict(primary)
    sources = {r.get(source_key, "unknown") for r in sorted_records}
    merged[source_key] = merge_sources(list(sources))
    # 参与合并的去重源数量，供多源交叉验证加成使用（DATA_SCORING_DICT §166/§175）
    existing_count = merged.get("source_count")
    merged["source_count"] = max(
        1,
        len(sources),
        existing_count if isinstance(existing_count, int) else 1,
    )

    # 存在性 / 规模类字段：全源 OR / max（"没看到"不构成与"看到了"的冲突），
    # 但 manual/api 的显式取值直接采信——见文件顶部的规则说明。
    #
    # 布尔证据（原实现只合并 4 个字段，其余 v1.2–v1.4 信号只取 primary，
    # 导致 galxe/layer3 等携带的任务入口与显式空投提及被静默丢弃）
    for field in _MERGE_BOOL_OR:
        override = _authoritative_value(sorted_records, field, source_key)
        if override is not _NO_VALUE:
            merged[field] = bool(override)
        elif any(field in r for r in sorted_records):
            merged[field] = any(bool(r.get(field)) for r in sorted_records)

    # 数值证据：取最大 / 取最小
    for field in _MERGE_NUMERIC_MAX:
        override = _authoritative_value(sorted_records, field, source_key)
        if isinstance(override, (int, float)) and not isinstance(override, bool):
            merged[field] = override
            continue
        values = [r[field] for r in sorted_records if isinstance(r.get(field), (int, float))]
        if values:
            merged[field] = max(values)
    for field in _MERGE_NUMERIC_MIN:
        override = _authoritative_value(sorted_records, field, source_key)
        if isinstance(override, (int, float)) and not isinstance(override, bool):
            merged[field] = override
            continue
        values = [r[field] for r in sorted_records if isinstance(r.get(field), (int, float))]
        if values:
            merged[field] = min(values)

    # 列表：全源并集，按来源优先级顺序去重保序
    for field in _MERGE_LIST_UNION:
        combined: list = []
        for record in sorted_records:
            value = record.get(field)
            if isinstance(value, list):
                for item in value:
                    if item not in combined:
                        combined.append(item)
        if combined or any(field in r for r in sorted_records):
            merged[field] = combined

    # 标量：优先级最高且值已知的源（跳过 unknown 占位）
    for field in _MERGE_SCALAR_BEST_KNOWN:
        best = _known_field_records(sorted_records, field, source_key)
        if best:
            merged[field] = best[0][field]

    # Merge discovery_score: take max
    scores = [r.get("discovery_score", 0.0) for r in sorted_records if r.get("discovery_score") is not None]
    merged["discovery_score"] = max(scores) if scores else 0.0

    # Merge auto_discovered: True if any source is auto-discovered
    auto_discovered = any(r.get("auto_discovered") for r in sorted_records if r.get("auto_discovered") is not None)
    merged["auto_discovered"] = auto_discovered

    # Merge discovered_at: earliest non-null
    #
    # 必须按可比的排序键取最小，不能直接 min() 原值：同一合并组里可能同时出现
    # 带时区与不带时区的 datetime（例如 SQLite `datetime('now')` 写出的裸字符串
    # 与采集器写出的 aware 值），`min()` 会抛
    # `TypeError: can't compare offset-naive and offset-aware datetimes`。
    # 而 `_dedup_records` 的合并调用不在任何逐行 try 里——一条记录就能中断整批采集。
    discovered_ats = [r.get("discovered_at") for r in sorted_records if r.get("discovered_at")]
    if discovered_ats:
        merged["discovered_at"] = min(discovered_ats, key=_discovered_at_sort_key)

    return merged


if __name__ == "__main__":
    # Test normalization
    print("=== Testing Normalization ===")

    # Name normalization tests
    test_names = [
        "LayerX",
        "Layer-X Finance",
        "Layer X Protocol",
        "layer2 finance",
        "LAYER2-PROTOCOL",
    ]

    for name in test_names:
        normalized = normalize_name(name)
        print(f"{name:30} -> {normalized}")

    print("\n=== Testing Sector Normalization ===")

    test_sectors = [
        "layer2",
        "L2",
        "restaking",
        "DeFi",
        "Unknown Sector",
    ]

    for sector in test_sectors:
        normalized = normalize_sector(sector)
        print(f"{sector:20} -> {normalized}")

    print("\n=== Testing Dedup Key ===")

    # Same project, different formats
    projects = [
        ("LayerX", "L2"),
        ("Layer-X Finance", "layer2"),
        ("Layer X Protocol", "Layer 2"),
    ]

    keys = [create_dedup_key(name, sector) for name, sector in projects]
    ids = [generate_deterministic_id(key) for key in keys]

    for (name, sector), key, proj_id in zip(projects, keys, ids, strict=False):
        print(f"{name:30} ({sector:10}) -> {key.to_string():20} -> {proj_id}")

    print(f"\nAll IDs same? {len(set(ids)) == 1}")

    print("\n=== Testing Source Priority ===")

    sources = ["twitter", "seed", "cryptorank", "defillama", "seed"]
    merged = merge_sources(sources)
    print(f"Sources: {sources}")
    print(f"Merged:  {merged}")
