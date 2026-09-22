"""Unit tests for Hunter Persona & Adaptive Weights Service and API."""

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.hunter_personas import (
    PERSONA_CONFIGS,
    HunterPersonaId,
    calculate_persona_score,
    get_all_personas_metadata,
)


def test_persona_weights_sum_to_one():
    """验证所有角色权重字典的权重之和严格等于 1.0 (精度误差 < 1e-6)."""
    for persona_id, config in PERSONA_CONFIGS.items():
        weights = config["weights"]
        total_weight = sum(weights.values())
        assert abs(total_weight - 1.0) < 1e-6, f"{persona_id} weights do not sum to 1.0: {total_weight}"
        assert len(weights) == 8, f"{persona_id} does not have all 8 dimensions"


def test_get_all_personas_metadata():
    """验证角色元数据导出格式."""
    metadata = get_all_personas_metadata()
    assert len(metadata) == 4
    ids = {m["id"] for m in metadata}
    assert ids == {"balanced", "zero_cost", "whale_restaking", "high_beta"}


def test_calculate_persona_score_balanced():
    """验证平衡模式下保持原基准分."""
    project = {
        "score": 75,
        "label": "FARM",
        "sub_scores": {
            "airdrop_signal": 80,
            "narrative_timing": 70,
            "team_reputation": 70,
            "risk": 70,
            "tokenomics": 70,
            "competition": 60,
            "execution": 75,
            "transparency": 80,
        },
    }
    result = calculate_persona_score(project, HunterPersonaId.BALANCED)
    assert result["persona_applied"] == "balanced"
    assert result["persona_score"] == 75
    assert result["score_delta"] == 0


def test_calculate_persona_score_zero_cost_boost():
    """验证零成本测试网角色下，测试网项目获得显著加分."""
    project = {
        "score": 60,
        "label": "WATCH",
        "stage": "testnet",
        "sub_scores": {
            "airdrop_signal": 85,
            "execution": 80,
            "narrative_timing": 70,
            "risk": 60,
            "transparency": 70,
            "team_reputation": 50,
            "tokenomics": 50,
            "competition": 50,
        },
        "meta": {
            "signals": {
                "has_testnet": True,
                "faucet_url": "https://faucet.testnet.io",
            }
        },
    }
    result = calculate_persona_score(project, HunterPersonaId.ZERO_COST)
    assert result["persona_applied"] == "zero_cost"
    assert result["persona_score"] > 60
    assert "测试网" in result["persona_boost_reason"]
    assert "水龙头" in result["persona_boost_reason"]


def test_calculate_persona_score_whale_restaking_boost():
    """验证巨鲸角色下，顶级机构参投且大额融资项目获得加分."""
    project = {
        "score": 65,
        "label": "FARM",
        "stage": "mainnet",
        "sub_scores": {
            "team_reputation": 90,
            "risk": 85,
            "tokenomics": 80,
            "airdrop_signal": 60,
            "execution": 70,
            "transparency": 70,
            "narrative_timing": 60,
            "competition": 50,
        },
        "funding": {
            "funding_tier": "tier-1",
            "funding_total_usd": 25_000_000,
        },
        "meta": {
            "signals": {
                "tvl": 50_000_000,
            }
        },
    }
    result = calculate_persona_score(project, HunterPersonaId.WHALE_RESTAKING)
    assert result["persona_applied"] == "whale_restaking"
    assert result["persona_score"] >= 75
    assert "顶级机构" in result["persona_boost_reason"]


def test_calculate_persona_score_high_beta_boost():
    """验证高弹性叙事角色下，早期热门赛道获得加分."""
    project = {
        "score": 68,
        "label": "FARM",
        "stage": "early",
        "sub_scores": {
            "narrative_timing": 95,
            "airdrop_signal": 85,
            "execution": 70,
            "team_reputation": 60,
            "tokenomics": 65,
            "risk": 50,
            "competition": 50,
            "transparency": 50,
        },
    }
    result = calculate_persona_score(project, HunterPersonaId.HIGH_BETA)
    assert result["persona_applied"] == "high_beta"
    assert result["persona_score"] >= 75
    assert "早期阶段" in result["persona_boost_reason"]


@pytest.fixture
def client():
    app = create_app()
    return TestClient(app)


def test_api_get_personas(client):
    """测试 GET /api/v1/projects/personas 端点."""
    response = client.get("/api/v1/projects/personas")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    personas = data["data"]["personas"]
    assert len(personas) == 4
    persona_ids = [p["id"] for p in personas]
    assert "zero_cost" in persona_ids
    assert "whale_restaking" in persona_ids
    assert "high_beta" in persona_ids
    assert "balanced" in persona_ids


def test_api_list_projects_with_persona(client):
    """测试 GET /api/v1/projects?persona=zero_cost 参数支持."""
    response = client.get("/api/v1/projects?persona=zero_cost&page_size=5")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    res_data = data["data"]
    assert res_data["filters"]["persona"] == "zero_cost"
    projects = res_data["projects"]
    if projects:
        first = projects[0]
        assert "persona_applied" in first
        assert "persona_score" in first
        assert "persona_label" in first
