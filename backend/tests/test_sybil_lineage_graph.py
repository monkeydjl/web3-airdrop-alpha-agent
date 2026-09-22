import pytest
from app.services.sybil_lineage_graph import analyze_wallet_lineage


def test_analyze_wallet_lineage_single_or_empty():
    res_single = analyze_wallet_lineage(["0x1111111111111111111111111111111111111111"])
    assert res_single["ok"] is True
    assert res_single["isolation_score"] == 100
    assert res_single["sybil_cluster_detected"] is False

    res_empty = analyze_wallet_lineage([])
    assert res_empty["ok"] is True
    assert res_empty["isolation_score"] == 100


def test_analyze_wallet_lineage_multiple_wallets():
    wallets = [
        "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        "0xcccccccccccccccccccccccccccccccccccccccc",
    ]
    res = analyze_wallet_lineage(wallets)
    assert res["ok"] is True
    assert 0 <= res["isolation_score"] <= 100
    assert len(res["nodes"]) >= 3
    assert "risk_level" in res
    assert "analysis_summary" in res
    assert len(res["recommendations"]) > 0
