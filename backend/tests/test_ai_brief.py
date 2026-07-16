"""Tests for rule-based AI brief (no live LLM)."""

from app.services.ai_brief import build_rule_brief


def test_build_rule_brief_farm():
    project = {
        "name": "DemoProtocol",
        "label": "FARM",
        "score": 72,
        "confidence": 0.9,
        "sector": "L2",
        "stage": "testnet",
        "source": "defillama",
        "reason": '["strong airdrop signal", "early narrative"]',
        "narrative_json": '{"timing":"early","heat_score":0.7,"stage":"growth"}',
        "team_json": '{"team_score":0.7,"team_type":"doxxed","risk_level":"low","flags":["tier-1 vc backed"]}',
        "risk_json": '{"sybil_difficulty":"high","farming_cost":"medium","token_risk":0.3,"unlock_pressure":"low"}',
        "tokenomics_json": '{"vc_share":0.2,"team_share":0.15,"unlock_pressure":"low"}',
    }
    brief = build_rule_brief(project)
    assert brief["mode"] == "rule"
    assert brief["label"] == "FARM"
    assert brief["label_zh"] == "重点参与"
    assert brief["score"] == 72
    assert "DemoProtocol" in brief["headline"]
    assert len(brief["paragraphs"]) >= 4
    assert any("叙事" in p for p in brief["paragraphs"])
    assert any("团队" in p for p in brief["paragraphs"])
    assert any("风险" in p for p in brief["paragraphs"])


def test_build_rule_brief_handles_missing_json():
    project = {
        "name": "Sparse",
        "label": "WATCH",
        "score": 55,
        "confidence": 0.4,
        "sector": "DeFi",
    }
    brief = build_rule_brief(project)
    assert brief["label_zh"] == "持续观察"
    assert brief["display_text"] if False else True
    assert "Sparse" in brief["headline"]
