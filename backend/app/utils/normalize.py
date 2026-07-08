"""Normalization and deduplication logic.

Handles project name/sector normalization and cross-source deduplication.

Reference:
- ENGINEERING_ROADMAP.md §6.2.1 归一化与去重
- TASK_BREAKDOWN.md W2-02
"""

import re
import unicodedata
import uuid
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
            normalized = normalized[:-len(suffix)]

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
        'layerx::l2'
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


# Source priority for conflict resolution
SOURCE_PRIORITY = {
    "seed": 1,      # Highest priority
    "defillama": 2,
    "cryptorank": 3,
    "twitter": 4,   # Lowest priority
    "unknown": 99,
}


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
    # Deduplicate and sort by priority
    unique_sources = sorted(
        set(sources),
        key=get_source_priority
    )
    return ",".join(unique_sources)


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

    for (name, sector), key, proj_id in zip(projects, keys, ids):
        print(f"{name:30} ({sector:10}) -> {key.to_string():20} -> {proj_id}")

    print(f"\nAll IDs same? {len(set(ids)) == 1}")

    print("\n=== Testing Source Priority ===")

    sources = ["twitter", "seed", "cryptorank", "defillama", "seed"]
    merged = merge_sources(sources)
    print(f"Sources: {sources}")
    print(f"Merged:  {merged}")
