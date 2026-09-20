"""Tests for Zero-Cost Testnet Priority & Faucet Hub."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repository import ProjectRepository, is_zero_cost_opportunity
from app.services.participation_tasks import generate_participation_tasks


def test_is_zero_cost_opportunity():
    """Verify criteria for zero-cost testnet opportunities."""
    # 1. Valid zero-cost testnet project
    valid = {
        "id": "p-testnet-ok",
        "stage": "testnet",
        "meta": json.dumps({"signals": {"has_testnet": True}, "viability_tier": "viable"}),
        "reason": json.dumps(["strong airdrop signal"]),
    }
    assert is_zero_cost_opportunity(valid) is True

    # 2. Borderline viability is still allowed if it's testnet
    borderline = {
        "id": "p-testnet-borderline",
        "stage": "testnet",
        "meta": json.dumps({"signals": {"has_testnet": True}, "viability_tier": "borderline"}),
        "reason": json.dumps([]),
    }
    assert is_zero_cost_opportunity(borderline) is True

    # 3. No testnet -> False
    no_testnet = {
        "id": "p-mainnet-only",
        "stage": "mainnet",
        "meta": json.dumps({"signals": {"has_testnet": False}, "viability_tier": "viable"}),
        "reason": json.dumps([]),
    }
    assert is_zero_cost_opportunity(no_testnet) is False

    # 4. Unviable viability tier -> False
    unviable = {
        "id": "p-unviable-testnet",
        "stage": "testnet",
        "meta": json.dumps({"signals": {"has_testnet": True}, "viability_tier": "unviable"}),
        "reason": json.dumps([]),
    }
    assert is_zero_cost_opportunity(unviable) is False

    # 5. Has LOW_RUNWAY_RISK or HEAVY_CAPITAL_LOCKUP -> False
    risk_reason = {
        "id": "p-risk-testnet",
        "stage": "testnet",
        "meta": json.dumps({"signals": {"has_testnet": True}, "viability_tier": "viable"}),
        "reason": json.dumps(["LOW_RUNWAY_RISK"]),
    }
    assert is_zero_cost_opportunity(risk_reason) is False

    lockup_reason = {
        "id": "p-lockup-testnet",
        "stage": "testnet",
        "meta": json.dumps({"signals": {"has_testnet": True}, "viability_tier": "viable"}),
        "reason": json.dumps(["HEAVY_CAPITAL_LOCKUP"]),
    }
    assert is_zero_cost_opportunity(lockup_reason) is False


def test_faucet_task_generated_for_testnet():
    """Verify that testnet-faucet-guide task is generated when project has testnet."""
    project = {
        "id": "p-testnet-faucet",
        "name": "Testnet Project",
        "has_testnet": True,
        "stage": "testnet",
        "url": "https://example.com",
    }
    checklist = generate_participation_tasks(project)
    tasks = checklist["tasks"]
    task_ids = [t["id"] for t in tasks]

    assert "testnet-faucet-guide" in task_ids
    faucet_task = next(t for t in tasks if t["id"] == "testnet-faucet-guide")
    assert faucet_task["category"] == "testnet"
    assert "水龙头" in faucet_task["title"]
    assert faucet_task["required"] is True


def test_api_list_projects_zero_cost_only():
    """Verify GET /api/v1/projects?zero_cost_only=true returns 200 and reflects filter."""
    client = TestClient(app)
    resp = client.get("/api/v1/projects?zero_cost_only=true")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "data" in body
    assert body["data"]["filters"]["zero_cost_only"] is True
    assert isinstance(body["data"]["projects"], list)
