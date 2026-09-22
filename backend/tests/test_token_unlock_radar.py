import pytest
from app.services.token_unlock_radar import (
    calculate_pressure_rating,
    get_upcoming_unlocks,
    get_project_unlock_details,
)


def test_calculate_pressure_rating():
    assert calculate_pressure_rating(20.0, 10_000_000.0) == "critical"
    assert calculate_pressure_rating(1.0, 150_000_000.0) == "critical"
    assert calculate_pressure_rating(8.0, 10_000_000.0) == "high"
    assert calculate_pressure_rating(3.0, 15_000_000.0) == "moderate"
    assert calculate_pressure_rating(1.0, 2_000_000.0) == "low"


def test_get_upcoming_unlocks():
    items = get_upcoming_unlocks(limit=5)
    assert len(items) <= 5
    assert len(items) > 0
    first = items[0]
    assert "token_symbol" in first
    assert "pressure_rating" in first
    assert "circulating_supply_pct" in first


def test_get_upcoming_unlocks_filtering():
    critical_items = get_upcoming_unlocks(min_pressure="critical")
    for item in critical_items:
        assert item["pressure_rating"] == "critical"


def test_get_project_unlock_details():
    celestia = get_project_unlock_details("celestia")
    assert celestia is not None
    assert celestia["token_symbol"] == "TIA"
    assert celestia["pressure_rating"] == "critical"

    unknown = get_project_unlock_details("non-existent-xyz-999")
    assert unknown is None
