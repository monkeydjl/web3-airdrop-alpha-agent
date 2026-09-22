"""API tests for Batch 3 Advanced Endpoints:
1. Faucets live probe (/api/v1/faucets/probe)
2. Bridge Optimizer (/api/v1/bridge/supported-chains & /api/v1/bridge/route)
3. Enriched Alpha Dossier (/api/v1/projects/{id}/dossier)
4. Project Comparison (/api/v1/projects/compare)
"""

from fastapi.testclient import TestClient
from app.db import get_connection, init_db
from app.main import create_app


def test_batch3_api_endpoints():
    init_db()
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO projects (
                id, name, sector, stage, score, label, confidence, sub_scores, reason, meta, url
            ) VALUES
            (
                'b3-proj-01', 'Arbitrum Nitro', 'Layer 2', 'mainnet', 92, 'FARM', 0.95,
                '{"narrative": 90, "team": 95, "funding": 90, "execution": 95, "tokenomics": 90, "sybil_resistance": 85, "viability": 95, "capital_efficiency": 85}',
                '["Massive TVL", "High activity"]',
                '{"signals": {"funding_total_usd": 150000000, "has_testnet": true}}',
                'https://arbitrum.io'
            ),
            (
                'b3-proj-02', 'Base Network', 'Layer 2', 'mainnet', 89, 'FARM', 0.92,
                '{"narrative": 95, "team": 90, "funding": 85, "execution": 90, "tokenomics": 85, "sybil_resistance": 90, "viability": 95, "capital_efficiency": 90}',
                '["Coinbase backed", "Fast growing"]',
                '{"signals": {"funding_total_usd": 0, "has_testnet": true}}',
                'https://base.org'
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    app = create_app()
    client = TestClient(app)

    import time
    from app.services.faucet_registry import _PROBE_CACHE
    _PROBE_CACHE["timestamp"] = time.time()
    _PROBE_CACHE["data"] = [
        {
            "faucet_id": "sepolia-pow",
            "name": "Sepolia PoW Faucet",
            "chain": "sepolia",
            "status": "online",
            "latency_ms": 85,
            "status_code": 200,
            "probed_at": int(time.time()),
        }
    ]

    # 1. Faucets Live Probe
    res_faucets_probe = client.get("/api/v1/faucets/probe")
    assert res_faucets_probe.status_code == 200
    probe_data = res_faucets_probe.json()
    assert probe_data["ok"] is True
    assert "probes" in probe_data["data"]
    assert len(probe_data["data"]["probes"]) > 0

    # 2. Bridge Optimizer
    res_bridge_chains = client.get("/api/v1/bridge/supported-chains")
    assert res_bridge_chains.status_code == 200
    chains_data = res_bridge_chains.json()
    assert chains_data["ok"] is True
    assert len(chains_data["chains"]) >= 8

    res_bridge_route = client.post(
        "/api/v1/bridge/route",
        json={
            "source_chain": "arbitrum",
            "target_chain": "base",
            "token": "ETH",
            "amount": 0.5,
        },
    )
    assert res_bridge_route.status_code == 200
    route_data = res_bridge_route.json()
    assert route_data["ok"] is True
    assert route_data["data"]["cheapest_route"] is not None
    assert len(route_data["data"]["routes"]) >= 4

    # 3. Enriched Alpha Dossier
    res_dossier = client.get("/api/v1/projects/b3-proj-01/dossier")
    assert res_dossier.status_code == 200
    dossier_data = res_dossier.json()
    assert dossier_data["ok"] is True
    assert "markdown" in dossier_data["data"]
    # Check enriched sections exist in markdown
    md = dossier_data["data"]["markdown"]
    assert "## 1. 📌 项目基本面与叙事定位" in md
    assert "## 7. ⛽ 全链实时 Gas 极佳交互窗口建议" in md
    assert "## 8. 🛡️ 智能合约与防钓鱼安全体检" in md
    assert "## 9. ⚡ 防女巫 CLI 自动化交互脚本建议" in md

    # 4. Project Comparison
    res_compare = client.get("/api/v1/projects/compare?ids=b3-proj-01,b3-proj-02")
    assert res_compare.status_code == 200
    compare_data = res_compare.json()
    assert compare_data["ok"] is True
    assert len(compare_data["projects"]) == 2
    assert len(compare_data["dimensions"]) == 8
    assert len(compare_data["radar_axes"]) == 8
    assert "winner_overall_name" in compare_data["verdict"]
