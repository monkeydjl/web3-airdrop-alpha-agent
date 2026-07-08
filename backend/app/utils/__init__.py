"""Utility modules."""

from app.utils.fetcher import (
    fetch,
    clear_cache,
    get_circuit_breaker_state,
    reset_circuit_breaker,
)

__all__ = [
    "fetch",
    "clear_cache",
    "get_circuit_breaker_state",
    "reset_circuit_breaker",
]
