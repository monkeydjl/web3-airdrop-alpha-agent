"""Unit tests for Project Comparison Service."""

import pytest
from app.db import get_connection, init_db
from app.services.project_comparison import compare_projects


@pytest.fixture(autouse=True)
def setup_comparison_data():
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (
                id, name, sector, stage, score, label, confidence, sub_scores, reason, meta
            ) VALUES
            (
                'pk-test-01', 'HyperChain L1', 'Layer 1', 'testnet', 88, 'FARM', 0.9,
                '{"narrative": 85, "team": 90, "funding": 95, "execution": 80, "tokenomics": 85, "sybil_resistance": 80, "viability": 90, "capital_efficiency": 75}',
                '["Tier-1 VC backed", "High TVL"]',
                '{"signals": {"funding_total_usd": 120000000, "has_testnet": true}}'
            ),
            (
                'pk-test-02', 'MicroDEX Protocol', 'DeFi', 'mainnet', 76, 'WATCH', 0.8,
                '{"narrative": 75, "team": 70, "funding": 60, "execution": 85, "tokenomics": 75, "sybil_resistance": 85, "viability": 75, "capital_efficiency": 90}',
                '["Community driven", "Low gas cost"]',
                '{"signals": {"funding_total_usd": 8000000, "has_testnet": false}}'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def test_compare_two_projects():
    res = compare_projects(["pk-test-01", "pk-test-02"])
    assert res["ok"] is True
    assert len(res["projects"]) == 2
    assert len(res["dimensions"]) == 8
    assert len(res["radar_axes"]) == 8
    assert res["verdict"]["winner_overall_id"] == "pk-test-01"
    assert "best_for_low_capital_name" in res["verdict"]
    assert len(res["verdict"]["tradeoffs"]) >= 2


def test_compare_empty_raises():
    with pytest.raises(ValueError):
        compare_projects([])
