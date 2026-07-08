"""Utility modules."""

from app.utils.fetcher import (
    fetch,
    clear_cache,
    get_circuit_breaker_state,
    reset_circuit_breaker,
)

from app.utils.normalize import (
    normalize_name,
    normalize_sector,
    create_dedup_key,
    generate_deterministic_id,
    get_source_priority,
    merge_sources,
    DedupKey,
    SECTOR_ALIAS,
)

__all__ = [
    # Fetcher
    "fetch",
    "clear_cache",
    "get_circuit_breaker_state",
    "reset_circuit_breaker",
    # Normalization
    "normalize_name",
    "normalize_sector",
    "create_dedup_key",
    "generate_deterministic_id",
    "get_source_priority",
    "merge_sources",
    "DedupKey",
    "SECTOR_ALIAS",
]
