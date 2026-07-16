"""Utility modules."""

from app.utils.fetcher import (
    clear_cache,
    fetch,
    get_circuit_breaker_state,
    reset_circuit_breaker,
)
from app.utils.normalize import (
    SECTOR_ALIAS,
    DedupKey,
    create_dedup_key,
    generate_deterministic_id,
    get_source_priority,
    merge_sources,
    normalize_name,
    normalize_sector,
)

__all__ = [
    "SECTOR_ALIAS",
    "DedupKey",
    "clear_cache",
    "create_dedup_key",
    "fetch",
    "generate_deterministic_id",
    "get_circuit_breaker_state",
    "get_source_priority",
    "merge_sources",
    "normalize_name",
    "normalize_sector",
    "reset_circuit_breaker",
]
